"""Phase 6 · CSRF double-submit middleware.

Contract:
- Every state-changing method (POST/PUT/PATCH/DELETE) under `/api/v1/*` MUST
  send `X-CSRF-Token` header whose value equals the JS-readable `oppos_csrf`
  cookie. Anything else → 403 `csrf_invalid`.
- GET/HEAD/OPTIONS bypass.
- Login / signup routes bypass — no session/CSRF exists before login.
- Internal routes (`/api/internal/*`) bypass — they authenticate via the
  header `X-Service-Token` instead.
- Webhook routes (`/api/webhook/*`) bypass — they authenticate via Stripe
  signatures.
- Bearer-authenticated requests bypass (CI test issuer + internal service
  tokens). This is safe because Bearer requires knowledge of the token, and
  Bearer is scoped to CI and internal paths only per config.
"""
from __future__ import annotations

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.config import settings

log = logging.getLogger("oppos.csrf")

_STATE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_BYPASS_PREFIXES = ("/api/internal/", "/api/webhook/")
_BYPASS_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/signup",
    # Google Sign-In bootstrap: same rationale as login/signup — the client
    # has no session yet, therefore no CSRF cookie.
    "/api/v1/auth/google/session",
    "/api/v1/auth/google/complete",
    # Legacy — some CI probes still POST /api/v1/consents while establishing a
    # signup flow; new signup path already covers this via the signup endpoint,
    # but keep the login/signup exempt only. Everything else state-changing MUST
    # carry CSRF.
}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        method = request.method.upper()
        path = request.url.path

        if method not in _STATE_METHODS:
            return await call_next(request)

        # Path-based exemptions.
        if path in _BYPASS_PATHS:
            return await call_next(request)
        if any(path.startswith(p) for p in _BYPASS_PREFIXES):
            return await call_next(request)

        # Bearer path — CI-only test issuer or the internal-service token both
        # arrive on the Authorization header. If Bearer is present, skip CSRF
        # (Bearer is proof of knowledge on its own).
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return await call_next(request)

        # Cookie-authenticated path → require CSRF double-submit.
        cookie_val = request.cookies.get(settings.CSRF_COOKIE_NAME, "")
        header_val = request.headers.get(settings.CSRF_HEADER_NAME, "")
        if not cookie_val or not header_val or cookie_val != header_val:
            return JSONResponse(
                status_code=403,
                content={"detail": {"error": "csrf_invalid",
                                     "message": "Missing or mismatched CSRF token."}},
            )
        return await call_next(request)
