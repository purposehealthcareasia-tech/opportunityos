from fastapi import HTTPException, Response, status
from core.config import settings
from core.security import verify_password, hash_password
from core import sessions as session_store
from domains.auth import repository as user_repo
from domains.audit import service as audit
from domains.users.models import UpdateProfileRequest, ChangePasswordRequest


async def update_profile(user: dict, req: UpdateProfileRequest) -> dict:
    updates: dict = {}
    if req.name is not None:
        updates["name"] = req.name.strip()
    if updates:
        await user_repo.update_profile(user["id"], updates)
        await audit.write(user["id"], "user.profile_update", f"user:{user['id']}", updates)
    fresh = await user_repo.by_id(user["id"])
    return {
        "id": fresh["id"],
        "email": fresh["email"],
        "name": fresh["name"],
        "role": user.get("role", "user"),
        "passport_activated": fresh.get("passport_activated", False),
        "created_at": fresh["created_at"],
    }


async def change_password(user: dict, req: ChangePasswordRequest, response: Response) -> None:
    """SEC-002: password change MUST invalidate every OTHER live session for
    this user (defence against a stolen-session attacker persisting after the
    victim rotates their password). The current session is rotated in-place —
    caller keeps its cookie, everyone else must re-login.
    """
    full = await user_repo.by_email(user["email"])
    if not full or not verify_password(req.current_password, full.get("password_hash", "")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="current_password_incorrect")
    await user_repo.update_password(user["id"], hash_password(req.new_password))

    # 1) Revoke every session for this user (including the current one).
    revoked = await session_store.revoke_all_for_user(user["id"])

    # 2) If the caller is on the cookie path, mint a fresh session so they stay
    #    logged in — anti-fixation. Bearer callers just re-login; there is no
    #    cookie to rotate.
    if user.get("_auth_mode") == "cookie":
        role = user.get("role") or "user"
        new_session = await session_store.create_session(
            user_id=user["id"], role=role,
        )
        kw = session_store.cookie_kwargs_for_role(role)
        response.set_cookie(settings.SESSION_COOKIE_NAME, new_session["session_id"], **kw)
        response.set_cookie(settings.CSRF_COOKIE_NAME, new_session["csrf_token"],
                             **{**kw, "httponly": False})
        await audit.write(user["id"], "auth.session_rotated",
                          f"session:{new_session['session_id']}",
                          {"via": "password_change"})

    await audit.write(user["id"], "user.password_change", f"user:{user['id']}",
                      {"sessions_revoked": revoked, "auth_mode": user.get("_auth_mode")})
