from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from typing import Optional
from domains.auth.models import SignupRequest, LoginRequest, PublicUser
from domains.auth import service as auth_svc
from domains.auth import google_service
from domains.auth import apple_service
from domains.auth import otp_service
from core.deps import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class GoogleSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)


class GoogleCompleteSignupRequest(BaseModel):
    pending_signup_id: str
    policy_text_version: str
    consents: dict[str, bool]


class AppleCompleteSignupRequest(BaseModel):
    pending_signup_id: str
    policy_text_version: str
    consents: dict[str, bool]


class OtpStartRequest(BaseModel):
    phone: str = Field(..., min_length=4, max_length=32)


class OtpVerifyRequest(BaseModel):
    phone: str = Field(..., min_length=4, max_length=32)
    code: str  = Field(..., min_length=4, max_length=10)


class OtpAttachRequest(BaseModel):
    phone: str = Field(..., min_length=4, max_length=32)
    code: str  = Field(..., min_length=4, max_length=10)


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


# ---------------------------------------------------------------------------
# Sign in with Apple (standards-based OIDC; CONFIGURATION_REQUIRED until
# Apple Developer credentials are provisioned).
# ---------------------------------------------------------------------------

@router.get("/apple/status")
async def apple_status():
    """Truthful public probe for the Apple provider state.

    Returns `{configured: bool}` — no secret values, no env values. Used by
    ops runbook / the frontend `Continue with Apple` disabled-state helper.
    Aligned with `GET /apple/start` (which returns 503 with
    `apple_auth_not_configured` when the same signal is false)."""
    required = ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID",
                "APPLE_PRIVATE_KEY", "APPLE_REDIRECT_URI")
    import os as _os
    configured = all(bool(_os.environ.get(k)) for k in required)
    return {"configured": configured, "provider": "apple_auth"}


@router.get("/apple/start")
async def apple_start(request: Request):
    """Return the Apple authorization URL for the frontend to navigate to.

    Returns 503 with `{error: "apple_auth_not_configured"}` when Apple env
    vars are absent — the frontend uses this to render an honest disabled
    state instead of a broken button.
    """
    return await apple_service.build_authorize_url(request)


@router.post("/apple/callback")
async def apple_callback(
    request: Request, response: Response,
    code: str = Form(...),
    state: str = Form(...),
    id_token: Optional[str] = Form(None),
    user: Optional[str] = Form(None),
):
    """Apple form_post callback. Apple hits this endpoint directly with the
    auth code — we exchange it, verify the id_token, and redirect the user
    back to a frontend route with either a set-cookie (existing user) or
    a pending_signup_id (new user needing consent)."""
    result = await apple_service.handle_callback(
        code=code, state=state, id_token_body=id_token, user_json=user,
        request=request, response=response,
    )
    # Redirect back to the frontend with the result encoded in the fragment.
    # Fragments never hit the server logs — safe for the pending_signup_id.
    from urllib.parse import urlencode
    import os as _os
    frontend_base = _os.environ.get("APPLE_FRONTEND_CALLBACK_URL", "/apple/callback")
    if result.get("status") == "logged_in":
        return RedirectResponse(url=f"{frontend_base}#status=logged_in", status_code=303)
    if result.get("status") == "pending_consent":
        q = urlencode({
            "status": "pending_consent",
            "pending_signup_id": result["pending_signup_id"],
            "email": result["email"],
            "is_private_email": "1" if result["is_private_email"] else "0",
        })
        return RedirectResponse(url=f"{frontend_base}#{q}", status_code=303)
    return result


@router.post("/apple/complete", status_code=201)
async def apple_complete_signup(
    req: AppleCompleteSignupRequest, request: Request, response: Response,
):
    """Finalise an Apple signup by submitting the five-scope consent map."""
    return await apple_service.complete_apple_signup(
        pending_signup_id=req.pending_signup_id,
        consents=req.consents,
        policy_text_version=req.policy_text_version,
        request=request, response=response,
    )


# ---------------------------------------------------------------------------
# Phone one-time code (Twilio Verify). CONFIGURATION_REQUIRED until Twilio
# env vars are provisioned — endpoints return 503 `otp_not_configured` so
# the frontend renders an honest disabled state.
# ---------------------------------------------------------------------------

@router.get("/otp/status")
async def otp_status():
    """Public — the frontend uses this to decide whether to render the OTP
    login section as active or as an honest 'coming soon' state."""
    from integrations import registry as _registry
    prov = _registry.get("twilio")
    if not prov:
        return {"ok": False, "configured": False,
                "reason": "provider_not_registered"}
    v = prov.validate_configuration()
    return {"ok": v.ok, "configured": v.ok,
            "missing": v.missing_env if not v.ok else []}


@router.post("/otp/start", status_code=200)
async def otp_start(req: OtpStartRequest, request: Request):
    return await otp_service.start_otp(phone=req.phone, request=request)


@router.post("/otp/verify")
async def otp_verify(req: OtpVerifyRequest, request: Request, response: Response):
    return await otp_service.verify_otp(
        phone=req.phone, code=req.code, request=request, response=response,
    )


@router.post("/otp/attach", status_code=200)
async def otp_attach(req: OtpAttachRequest, request: Request,
                     user: dict = Depends(get_current_user)):
    return await otp_service.attach_phone_to_user(
        user_id=user["id"], phone=req.phone, code=req.code, request=request,
    )
