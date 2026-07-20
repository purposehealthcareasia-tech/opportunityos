from fastapi import APIRouter, Depends
from domains.auth.models import SignupRequest, LoginRequest, TokenResponse, PublicUser
from domains.auth import service as auth_svc
from core.deps import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(req: SignupRequest):
    return await auth_svc.signup(req)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    return await auth_svc.login(req)


@router.get("/me", response_model=PublicUser)
async def me(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user.get("role", "user"),
        "passport_activated": user.get("passport_activated", False),
        "created_at": user["created_at"],
    }
