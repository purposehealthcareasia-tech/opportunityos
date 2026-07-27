"""Walk-in Route Log (Phase 3 Founder Brief).

For in-person / phone-in / paper application routes that don't have an online
apply URL, candidates need a way to log the fact that they showed up. This is an
append-only ledger tied to the `applications` table so the tracker + funnel see
these as first-class events.

Design:
  * A walk-in row is created via POST /api/v1/walkins with (employer, address,
    walked_in_at, notes, application_id?). If application_id is omitted, a
    lightweight companion application row is created in state="submitted" with
    route="walkin" so the funnel counts it.
  * Rows are immutable (no PATCH/DELETE). Corrections go via a NEW row that
    references superseded_by.

Rails:
  * Consent-gated on `track_applications` because it's a tracker write.
  * Reasonable rate-limit: at most 5 walk-ins per hour per user.
  * No employer PII beyond what the user typed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.deps import require_consent
from core.db import get_db
from core.time_utils import utc_now
from domains.audit import service as audit


router = APIRouter(prefix="/api/v1/walkins", tags=["walkins"])


class WalkInCreate(BaseModel):
    employer: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=400)
    walked_in_at: str | None = None  # ISO date; defaults to now
    notes: str | None = Field(default=None, max_length=2000)
    application_id: str | None = None
    outcome: str = Field(default="submitted",
                          pattern="^(submitted|got_application|screener_at_door|declined_intake)$")


async def _rate_limit(user_id: str) -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    n = await get_db().walkins.count_documents({"user_id": user_id, "created_at": {"$gte": since}})
    if n >= 5:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                             detail={"error": "walkin_rate_limited",
                                     "message": "You've logged 5 walk-ins in the last hour. Try again shortly.",
                                     "window_hours": 1, "cap": 5})


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_walkin(req: WalkInCreate,
                         user: dict = Depends(require_consent("track_applications"))):
    await _rate_limit(user["id"])
    db = get_db()
    now = utc_now()
    when = now
    if req.walked_in_at:
        try:
            when = datetime.fromisoformat(req.walked_in_at.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=422, detail={"error": "invalid_datetime",
                                                         "field": "walked_in_at"})

    # If no application_id was provided, create a lightweight companion row so
    # the funnel / tracker see this walk-in.
    application_id = req.application_id
    if not application_id:
        app_doc = {
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "job_id": None,
            "company_id": None,
            "job_snapshot": {"company_name": req.employer, "title": None,
                              "canonical_key": None, "is_sample": False,
                              "walkin": True},
            "state": "submitted" if req.outcome == "submitted" else "shortlisted",
            "route": "walkin",
            "route_rationale": "Candidate applied in person / walk-in route.",
            "materials": {},
            "authorization_id": None,
            "minutes_to_prepare": 0,
            "fields_corrected": None,
            "created_at": now,
            "updated_at": now,
        }
        await db.applications.insert_one(app_doc)
        application_id = app_doc["id"]

    row = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": application_id,
        "employer": req.employer.strip(),
        "address": (req.address or "").strip() or None,
        "walked_in_at": when,
        "outcome": req.outcome,
        "notes": (req.notes or "").strip() or None,
        "created_at": now,
        "superseded_by": None,
    }
    await db.walkins.insert_one(row)
    await audit.write(user["id"], "walkin.log", f"walkin:{row['id']}",
                       {"employer": row["employer"], "outcome": row["outcome"]})
    row.pop("_id", None)
    return row


@router.get("/mine")
async def list_mine(user: dict = Depends(require_consent("track_applications"))):
    rows: list[dict] = []
    async for r in get_db().walkins.find({"user_id": user["id"], "superseded_by": None},
                                          {"_id": 0}).sort("walked_in_at", -1):
        rows.append(r)
    return {"walkins": rows, "total": len(rows)}
