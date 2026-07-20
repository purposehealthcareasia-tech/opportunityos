import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from core.db import get_db
from core.deps import get_current_user, require_consent
from core.time_utils import utc_now
from domains.audit import service as audit

router = APIRouter(prefix="/api/v1/matches", tags=["matches"])


class FeedbackRequest(BaseModel):
    helpful: bool
    note: str | None = Field(default=None, max_length=500)


async def upsert(*, user_id: str, job_id: str, score: dict, gates: dict) -> bool:
    """Insert or update match_scores. Returns True if this was a NEW row (used for usage_meters)."""
    db = get_db()
    now = utc_now()
    existing = await db.match_scores.find_one({"user_id": user_id, "job_id": job_id})
    payload = {
        "user_id": user_id,
        "job_id": job_id,
        "score": score["score"],
        "confidence": score["confidence"],
        "reason_codes": score["reason_codes"],
        "gate_results": gates["gates"],
        "weights_version": score["weights_version"],
        "updated_at": now,
    }
    if existing:
        await db.match_scores.update_one({"_id": existing["_id"]}, {"$set": payload})
        return False
    payload["id"] = str(uuid.uuid4())
    payload["created_at"] = now
    await db.match_scores.insert_one(payload)
    return True


@router.get("/for-job/{job_id}")
async def get_score_for_job(job_id: str, user: dict = Depends(get_current_user)):
    row = await get_db().match_scores.find_one({"user_id": user["id"], "job_id": job_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="match_score_not_found")
    # Founder Fix Round-2 · P1 #4 — surface the user's LAST feedback (if any) so the modal
    # can reflect prior state without a separate call.
    fb = await get_db().score_feedback.find_one(
        {"user_id": user["id"], "job_id": job_id},
        sort=[("ts", -1)],
        projection={"_id": 0, "helpful": 1, "note": 1, "ts": 1, "id": 1},
    )
    row["feedback"] = fb  # None if no feedback yet
    return row


@router.post("/for-job/{job_id}/feedback", status_code=201)
async def feedback(job_id: str, req: FeedbackRequest, user: dict = Depends(get_current_user)):
    ms = await get_db().match_scores.find_one({"user_id": user["id"], "job_id": job_id}, {"_id": 0})
    if not ms:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="match_score_not_found")
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "job_id": job_id,
        "match_score_id": ms["id"],
        "helpful": bool(req.helpful),
        "note": req.note,
        "ts": utc_now(),
    }
    await get_db().score_feedback.insert_one(row)
    await audit.write(user["id"], "score.feedback", f"match_score:{ms['id']}", {"helpful": req.helpful})
    return {"ok": True, "id": row["id"], "helpful": row["helpful"]}
