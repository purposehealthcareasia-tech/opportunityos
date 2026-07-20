from fastapi import APIRouter, Depends, HTTPException, status
from core.deps import get_current_user, require_role
from domains.auth.models import PublicUser
from domains.users.models import UpdateProfileRequest, ChangePasswordRequest
from domains.users import service as users_svc
from domains.users import repository as users_repo
from domains.users.sealed import serialize_claims
from domains.auth import repository as user_repo

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=PublicUser)
async def get_me(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user.get("role", "user"),
        "passport_activated": user.get("passport_activated", False),
        "created_at": user["created_at"],
    }


@router.patch("/me", response_model=PublicUser)
async def update_me(req: UpdateProfileRequest, user: dict = Depends(get_current_user)):
    return await users_svc.update_profile(user, req)


@router.post("/me/change-password", status_code=204)
async def change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    await users_svc.change_password(user, req)
    return None


@router.get("/me/claims")
async def my_claims(user: dict = Depends(get_current_user)):
    claims = await users_repo.get_claims_for_user(user["id"])
    return {"claims": serialize_claims(claims, user["id"])}


@router.get("/{user_id}")
async def read_user(user_id: str, viewer: dict = Depends(require_role("admin", "support"))):
    """Admin/support view of a user. Sealed claim values are masked — admins do NOT see sealed values."""
    target = await user_repo.by_id(user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
    claims = await users_repo.get_claims_for_user(user_id)
    return {
        "user": {
            "id": target["id"],
            "email": target["email"],
            "name": target["name"],
            "passport_activated": target.get("passport_activated", False),
            "created_at": target["created_at"],
        },
        "claims": serialize_claims(claims, viewer["id"]),
    }
