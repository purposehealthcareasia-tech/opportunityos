from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from domains.auth.models import SignupRequest, LoginRequest, PublicUser
from domains.auth import service as auth_svc
from domains.auth import google_service
from core.deps import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class GoogleSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)


class GoogleCompleteSignupRequest(BaseModel):
    pending_signup_id: str
    policy_text_version: str
    consents: dict[str, bool]


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


@router.post("/google/session")
async def google_session(req: GoogleSessionRequest, request: Request, response: Response):
    """Exchange an Emergent Google-auth session_id for either an
    OpportunityOS login OR a pending-signup handle awaiting consent."""
    return await google_service.start_google_session(
        session_id=req.session_id, request=request, response=response,
    )


@router.post("/google/complete", status_code=201)
async def google_complete_signup(
    req: GoogleCompleteSignupRequest, request: Request, response: Response,
):
    """Finalise a Google signup by submitting the five-scope consent map."""
    return await google_service.complete_google_signup(
        pending_signup_id=req.pending_signup_id,
        consents=req.consents,
        policy_text_version=req.policy_text_version,
        request=request, response=response,
    )
