import hashlib
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from core.config import settings
from core.db import get_db
from core.security import decode_access_token
from core.time_utils import utc_now
from core import sessions as session_store

STATE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Idempotency for state-changing requests under /api/v1/*.

    SEC-003: user identity is resolved from BOTH the cookie session and the
    Bearer token — cookie-authenticated callers used to collapse into
    `user_id="anon"`, which meant two different browser users hitting the same
    endpoint with the same Idempotency-Key could receive each other's cached
    responses. This resolves the session cookie BEFORE building the cache key.

    Contract:
    - Read Idempotency-Key header (opt-in per client — no key = passthrough).
    - Resolve identity from cookie session → then Bearer → else "anon".
    - Anonymous callers are scoped by client IP so two unauthenticated signups
      with the same key from different clients don't collide either.
    - Cache responses with status < 400.
    - Replay cached response byte-for-byte on identical repeats.
    """

    async def _resolve_user_id(self, request: Request) -> str:
        # 1) Cookie session — production path.
        sid = request.cookies.get(settings.SESSION_COOKIE_NAME)
        if sid:
            sess = await session_store.get_session(sid)
            if sess and sess.get("user_id"):
                return sess["user_id"]
        # 2) Bearer token — CI test issuer / internal probes.
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            payload = decode_access_token(auth.split(" ", 1)[1].strip())
            if payload and payload.get("sub"):
                return payload["sub"]
        # 3) Anonymous — scope by client IP so cross-client collisions
        #    (e.g., two people signing up simultaneously) still isolate.
        ip = (request.client.host if request.client else None) or "unknown"
        return f"anon:{ip}"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method not in STATE_METHODS or not request.url.path.startswith("/api/v1/"):
            return await call_next(request)

        key = request.headers.get("Idempotency-Key")
        if not key:
            return await call_next(request)

        user_id = await self._resolve_user_id(request)
        cache_key = f"{user_id}:{request.method}:{request.url.path}:{key}"
        db = get_db()
        existing = await db.idempotency_records.find_one({"key": cache_key})
        if existing:
            return Response(
                content=existing["response_body"],
                status_code=existing["status_code"],
                media_type=existing.get("media_type", "application/json"),
                headers={"X-Idempotent-Replay": "true"},
            )

        response = await call_next(request)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        if response.status_code < 400:
            try:
                await db.idempotency_records.insert_one(
                    {
                        "key": cache_key,
                        "user_id": user_id,
                        "endpoint": request.url.path,
                        "method": request.method,
                        "status_code": response.status_code,
                        "media_type": response.headers.get("content-type", "application/json"),
                        "response_body": body,
                        "response_hash": hashlib.sha256(body).hexdigest(),
                        "created_at": utc_now(),
                    }
                )
            except Exception:
                # Duplicate key race — another concurrent request already cached. Safe to ignore.
                pass

        return Response(
            content=body,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/json"),
        )
