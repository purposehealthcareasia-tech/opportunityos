from fastapi import APIRouter, Depends
from core.deps import get_current_user
from core.policy import CONSENT_SCOPES
from domains.consent.models import ConsentChangeRequest, ConsentStateResponse
from domains.consent import service as consent_svc

router = APIRouter(prefix="/api/v1/consents", tags=["consent"])


@router.get("", response_model=ConsentStateResponse)
async def list_consents(user: dict = Depends(get_current_user)):
    return await consent_svc.state(user["id"])


@router.get("/scopes")
async def scope_catalog():
    """Public consent scope catalog for the signup screen."""
    return {"scopes": CONSENT_SCOPES}


@router.post("", status_code=201)
async def change_consent(req: ConsentChangeRequest, user: dict = Depends(get_current_user)):
    # Append-only law: the owning user can grant or revoke any scope at any time. Revocation
    # causes dependent endpoints to 403 consent_required until the user grants the scope again.
    row_id = await consent_svc.record(
        user_id=user["id"],
        scope=req.scope,
        granted=req.granted,
        policy_text_version=req.policy_text_version,
        actor=user["id"],
        source="settings",
    )
    return {"id": row_id, "scope": req.scope, "granted": req.granted}
