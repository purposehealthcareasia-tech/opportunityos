from fastapi import HTTPException, status
from core.security import verify_password, hash_password
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


async def change_password(user: dict, req: ChangePasswordRequest) -> None:
    full = await user_repo.by_email(user["email"])
    if not full or not verify_password(req.current_password, full.get("password_hash", "")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="current_password_incorrect")
    await user_repo.update_password(user["id"], hash_password(req.new_password))
    await audit.write(user["id"], "user.password_change", f"user:{user['id']}")
