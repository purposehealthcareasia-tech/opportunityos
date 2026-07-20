"""Phase 6 · Cookie-session first authentication.

Precedence:
1. Session cookie (`oppos_session`) → primary path for browser users.
2. Bearer JWT → ONLY if `CI_TEST_ISSUER_ENABLED=true` (pytest / CI probes).
   Hard-off in `PROD_MODE=true` by config assertion at server startup.
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from core.config import settings
from core.db import get_db
from core.security import decode_access_token
from core import sessions as session_store

bearer_scheme = HTTPBearer(auto_error=False)


async def _user_from_cookie(request: Request) -> dict | None:
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        return None
    sess = await session_store.get_session(session_id)
    if not sess:
        return None
    db = get_db()
    user = await db.users.find_one({"id": sess["user_id"]}, {"password_hash": 0})
    if not user:
        return None
    admin_row = await db.admin_users.find_one({"user_id": user["id"]})
    user["role"] = admin_row["role"] if admin_row else "user"
    # Stash session_id for downstream (logout, rotation).
    user["_session_id"] = sess["session_id"]
    user["_auth_mode"] = "cookie"
    return user


async def _user_from_bearer(creds: HTTPAuthorizationCredentials | None) -> dict | None:
    if not settings.CI_TEST_ISSUER_ENABLED:
        return None
    if creds is None or (creds.scheme or "").lower() != "bearer":
        return None
    payload = decode_access_token(creds.credentials)
    if not payload or not payload.get("sub"):
        return None
    db = get_db()
    user = await db.users.find_one({"id": payload["sub"]}, {"password_hash": 0})
    if not user:
        return None
    admin_row = await db.admin_users.find_one({"user_id": user["id"]})
    user["role"] = admin_row["role"] if admin_row else "user"
    user["_auth_mode"] = "bearer_ci"
    return user


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    # 1) Session cookie first.
    user = await _user_from_cookie(request)
    if user:
        return user
    # 2) CI-only Bearer fallback (pytest suite, internal probes).
    user = await _user_from_bearer(creds)
    if user:
        return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication_required")


def require_role(*allowed: str):
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="role_forbidden")
        return user
    return _check


def require_consent(scope: str):
    """Return the currently effective consent for `scope`. If not granted, raise 403 with a machine-readable body."""
    async def _check(user: dict = Depends(get_current_user)) -> dict:
        db = get_db()
        latest = await db.consent_records.find_one(
            {"user_id": user["id"], "scope": scope},
            sort=[("ts", -1)],
        )
        granted = bool(latest and latest.get("granted") is True)
        if not granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "consent_required",
                    "scope": scope,
                    "grant_url": "/api/v1/consents",
                },
            )
        return user
    return _check
