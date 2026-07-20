import hashlib
import json
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from core.db import get_db
from core.security import decode_access_token
from core.time_utils import utc_now

STATE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Idempotency for state-changing requests under /api/v1/*.

    - Reads Idempotency-Key header (opt-in per client — no key = passthrough).
    - Scopes cache key by (user_id or anon, method, path, key).
    - Caches responses with status < 400.
    - Replays cached response byte-for-byte on subsequent identical requests
      so no duplicate side-effects or audit rows are created.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method not in STATE_METHODS or not request.url.path.startswith("/api/v1/"):
            return await call_next(request)

        key = request.headers.get("Idempotency-Key")
        if not key:
            return await call_next(request)

        # Best-effort user identification
        user_id = "anon"
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            payload = decode_access_token(auth.split(" ", 1)[1].strip())
            if payload and payload.get("sub"):
                user_id = payload["sub"]

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
