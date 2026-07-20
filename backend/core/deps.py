from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from core.db import get_db
from core.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if creds is None or (creds.scheme or "").lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication_required")
    payload = decode_access_token(creds.credentials)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    db = get_db()
    user = await db.users.find_one({"id": payload["sub"]}, {"password_hash": 0})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")
    # attach role from admin_users if present
    admin_row = await db.admin_users.find_one({"user_id": user["id"]})
    user["role"] = admin_row["role"] if admin_row else "user"
    return user


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
