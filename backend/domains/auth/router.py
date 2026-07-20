from fastapi import APIRouter, Depends, Request, Response
from domains.auth.models import SignupRequest, LoginRequest, PublicUser
from domains.auth import service as auth_svc
from core.deps import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/signup", status_code=201)
async def signup(req: SignupRequest, request: Request, response: Response):
    return await auth_svc.signup(req, request, response)


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    return await auth_svc.login(req, request, response)


@router.post("/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    return await auth_svc.logout(user, response)


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
