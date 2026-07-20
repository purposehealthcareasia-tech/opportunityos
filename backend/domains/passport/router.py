from fastapi import APIRouter, Depends, HTTPException, status
from core.deps import get_current_user, require_consent
from core.db import get_db
from core.time_utils import utc_now
from domains.claims import repository as claims_repo
from domains.audit import service as audit

router = APIRouter(prefix="/api/v1/passport", tags=["passport"])


@router.get("/ping")
async def ping(user: dict = Depends(require_consent("process_career_data"))):
    return {
        "ok": True,
        "user_id": user["id"],
        "phase": 1,
        "note": "Consent-gated probe. Used to verify require_consent behavior in tests.",
    }


@router.get("/activation-status")
async def activation_status(user: dict = Depends(get_current_user)):
    """Compute the Activation checklist server-side so the UI reflects real truth, not local state."""
    approved = await claims_repo.approved_types(user["id"])
    has_identity = "identity" in approved
    has_edu_or_emp = "education" in approved or "employment" in approved
    fresh_user = await get_db().users.find_one({"id": user["id"]}, {"passport_activated": 1, "_id": 0})
    return {
        "requirements": {
            "identity_approved": has_identity,
            "education_or_employment_approved": has_edu_or_emp,
        },
        "can_activate": has_identity and has_edu_or_emp,
        "activated": bool(fresh_user and fresh_user.get("passport_activated")),
    }


@router.post("/activate", status_code=200)
async def activate(user: dict = Depends(require_consent("process_career_data"))):
    approved = await claims_repo.approved_types(user["id"])
    missing: list[str] = []
    if "identity" not in approved:
        missing.append("identity")
    if not ({"education", "employment"} & approved):
        missing.append("education_or_employment")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "activation_requirements_not_met",
                "missing_categories": missing,
                "hint": "Approve at least one identity claim AND at least one education-or-employment claim before activating.",
            },
        )
    await get_db().users.update_one(
        {"id": user["id"]},
        {"$set": {"passport_activated": True, "passport_activated_at": utc_now()}},
    )
    await audit.write(user["id"], "passport.activate", f"user:{user['id']}")
    return {"activated": True}
