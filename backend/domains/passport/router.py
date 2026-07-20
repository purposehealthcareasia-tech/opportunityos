from fastapi import APIRouter, Depends
from core.deps import get_current_user, require_consent

router = APIRouter(prefix="/api/v1/passport", tags=["passport"])


@router.get("/ping")
async def ping(user: dict = Depends(require_consent("process_career_data"))):
    """Phase-1 consent-gated probe. Real Passport endpoints land in Phase 2."""
    return {
        "ok": True,
        "user_id": user["id"],
        "phase": 1,
        "note": "Passport ingestion + approval flow lands in Phase 2.",
    }
