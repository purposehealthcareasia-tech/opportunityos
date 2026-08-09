"""Phase 5f · Interview Outcome Receipts.

Extends the receipt chain past application to interview lifecycle:

  interview_scheduled → interview_completed | interview_ghosted

Each event is HMAC-SHA256 signed with the same `EVIDENCE_SIGNING_KEY`
as the ghosting export, so third-party verifiers can validate all
receipts through ONE verify endpoint. `POST /api/v1/exports/verify-signature`
already exists (Phase 4); it accepts any canonical-serialized manifest.

Rails:
  * User-scoped only (interview receipts never surface cross-user).
  * Ghosting event auto-derived when scheduled interview is silent
    past `INTERVIEW_GHOST_THRESHOLD_DAYS` (default 14).
  * All events appended to `application_outcomes` (single ledger,
    single verify path).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.db import get_db
from core.deps import require_consent
from domains.exports.ghosting import _sign, canonical_serialize


router = APIRouter(prefix="/api/v1/interview-receipts", tags=["interview_receipts"])


INTERVIEW_GHOST_THRESHOLD_DAYS = int(
    os.environ.get("INTERVIEW_GHOST_THRESHOLD_DAYS", "14") or "14"
)

_EVENT_TYPES = ("interview_scheduled", "interview_completed", "interview_ghosted")


class RecordEventRequest(BaseModel):
    application_id: str = Field(..., min_length=8, max_length=64)
    event: Literal["interview_scheduled", "interview_completed"]
    at: Optional[str] = Field(
        None,
        description="ISO 8601 timestamp. Defaults to server-side now.",
    )
    notes: Optional[str] = Field(None, max_length=280)


@router.post("/record")
async def record_event(
    req: RecordEventRequest,
    user: dict = Depends(require_consent("track_applications")),
):
    db = get_db()
    app_row = await db.applications.find_one(
        {"id": req.application_id, "user_id": user["id"]},
        {"_id": 0},
    )
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")

    ts = _parse_ts(req.at) or datetime.now(timezone.utc)
    outcome_id = str(uuid.uuid4())
    row = {
        "id": outcome_id,
        "user_id": user["id"],
        "application_id": req.application_id,
        "event": req.event,
        "notes": (req.notes or "")[:280],
        "at": ts.isoformat(),
    }
    # Compute HMAC over canonical row (minus id — id is a random uuid,
    # not signing-relevant). Store the receipt-level signature so any
    # single-row export is verifiable independently.
    sign_body = {k: v for k, v in row.items() if k != "id"}
    row["signature"] = _sign(sign_body)
    row["signature_note"] = "HMAC-SHA256 over canonical body (excluding id)."
    await db.application_outcomes.insert_one(row)
    return {
        "recorded": True,
        "outcome_id": outcome_id,
        "event": req.event,
        "signature": row["signature"],
        "verify_endpoint": "POST /api/v1/exports/verify-signature",
    }


@router.get("/for-application/{application_id}")
async def list_events_for_application(
    application_id: str,
    user: dict = Depends(require_consent("track_applications")),
):
    db = get_db()
    app_row = await db.applications.find_one(
        {"id": application_id, "user_id": user["id"]},
        {"_id": 0},
    )
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")

    rows = []
    async for r in db.application_outcomes.find({
        "user_id": user["id"],
        "application_id": application_id,
        "event": {"$in": list(_EVENT_TYPES)},
    }).sort("at", 1):
        r.pop("_id", None)
        rows.append(r)

    # Auto-detect ghosting when the LAST event is `interview_scheduled`
    # and older than the threshold. We SURFACE the derived state but
    # DO NOT auto-write a receipt — user must explicitly acknowledge
    # (avoids background writes user didn't consent to at moment T).
    derived_ghost = None
    if rows:
        last = rows[-1]
        if last["event"] == "interview_scheduled":
            last_at = _parse_ts(last["at"])
            if last_at:
                age = datetime.now(timezone.utc) - last_at
                if age > timedelta(days=INTERVIEW_GHOST_THRESHOLD_DAYS):
                    derived_ghost = {
                        "would_be_ghosted": True,
                        "days_since_scheduled": round(age.total_seconds() / 86400.0, 1),
                        "threshold_days": INTERVIEW_GHOST_THRESHOLD_DAYS,
                        "notice": (
                            "The scheduled interview is past the ghost threshold. "
                            "Confirm here to mint an `interview_ghosted` receipt."
                        ),
                    }
    return {
        "application_id": application_id,
        "events": rows,
        "count": len(rows),
        "derived_ghosting_signal": derived_ghost,
        "verify_endpoint": "POST /api/v1/exports/verify-signature",
    }


class GhostConfirmRequest(BaseModel):
    application_id: str = Field(..., min_length=8, max_length=64)


@router.post("/confirm-ghost")
async def confirm_ghost(
    req: GhostConfirmRequest,
    user: dict = Depends(require_consent("track_applications")),
):
    """User-driven confirmation that a scheduled interview has been
    ghosted past threshold. Mints a signed `interview_ghosted` receipt.
    Never auto-fires — user must click."""
    db = get_db()
    scheduled = None
    async for r in db.application_outcomes.find({
        "user_id": user["id"],
        "application_id": req.application_id,
        "event": "interview_scheduled",
    }).sort("at", -1).limit(1):
        scheduled = r
    if not scheduled:
        raise HTTPException(status_code=409, detail={
            "error": "no_interview_scheduled",
            "message": "Confirm-ghost requires a prior `interview_scheduled` receipt on this application.",
        })
    sch_at = _parse_ts(scheduled["at"])
    if not sch_at or (datetime.now(timezone.utc) - sch_at) <= timedelta(days=INTERVIEW_GHOST_THRESHOLD_DAYS):
        raise HTTPException(status_code=409, detail={
            "error": "not_yet_past_threshold",
            "threshold_days": INTERVIEW_GHOST_THRESHOLD_DAYS,
        })
    now = datetime.now(timezone.utc)
    outcome_id = str(uuid.uuid4())
    row = {
        "id": outcome_id,
        "user_id": user["id"],
        "application_id": req.application_id,
        "event": "interview_ghosted",
        "notes": (
            f"User-confirmed. Silent {(now - sch_at).days} days after "
            f"interview_scheduled at {scheduled['at']}."
        ),
        "at": now.isoformat(),
    }
    row["signature"] = _sign({k: v for k, v in row.items() if k != "id"})
    row["signature_note"] = "HMAC-SHA256 over canonical body (excluding id)."
    await db.application_outcomes.insert_one(row)
    return {
        "recorded": True,
        "outcome_id": outcome_id,
        "signature": row["signature"],
        "verify_endpoint": "POST /api/v1/exports/verify-signature",
    }


def _parse_ts(v) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None
