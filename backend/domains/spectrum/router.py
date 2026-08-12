"""Phase 6b · Auto-spectrum suggestion router."""
from fastapi import APIRouter, Depends

from core.deps import get_current_user
from domains.spectrum import service as svc

router = APIRouter(prefix="/api/v1", tags=["spectrum"])


@router.get("/spectrum/suggest")
async def suggest(user: dict = Depends(get_current_user)):
    """Return a starter spectrum inferred from the caller's Passport
    (approved claims only). Titles / radius / pay-floor with an honest
    rationale for each. Never invents pay data.

    Consumed by the /onboarding/launch approve-&-launch screen (Batch D)
    to pre-fill the spectrum-confirm form. UI copy displays
    `honest_label` verbatim: "suggested from your Passport — edit anytime".
    """
    return await svc.suggest_spectrum(user["id"])
