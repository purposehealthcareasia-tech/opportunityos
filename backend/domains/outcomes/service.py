"""Outcomes + Interviews + Tracker + Inbound webhook.

Data models:
  outcomes:      { id, user_id, application_id, event, ts, source, note?, ext_message_id? }
  interviews:    { id, user_id, application_id, stage, scheduled_at?, qualified: bool|null,
                   created_at, updated_at, source }

Immutability: outcomes is APPEND-ONLY. No update / delete endpoint. Corrections are
new outcome rows.

State transition contract (tracker "log update" flow):
  submitted -> response -> interview -> offer -> closed
  Illegal transitions are rejected by the atomic-transition repository.

Event enum: viewed | response | interview_request | interview_scheduled | rejected | offer | hired | closed
Source enum: manual | parsed
"""
from __future__ import annotations
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from core.db import get_db
from core.deps import get_current_user, require_consent
from core.time_utils import utc_now
from domains.audit import service as audit
from domains.applications.repository import atomic_transition, ALLOWED_TRANSITIONS, InvalidTransition


router = APIRouter(prefix="/api/v1", tags=["tracker"])


EVENT_ENUM = {
    "viewed", "response", "interview_request", "interview_scheduled",
    "rejected", "offer", "hired", "closed",
}

# Map an outcome event onto the target application state (if any).
# The transition table (repository.ALLOWED_TRANSITIONS) still gates whether the
# transition is legal from the CURRENT state; illegal jumps 409.
EVENT_TO_STATE = {
    "viewed": None,
    "response": "response",
    "interview_request": "interview",
    "interview_scheduled": "interview",
    "rejected": "closed",
    "offer": "offer",
    "hired": "offer",  # not enough of a state to model 'hired' separately in v0.1
    "closed": "closed",
}


class LogOutcomeRequest(BaseModel):
    event: str = Field(..., min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


class ScheduleInterviewRequest(BaseModel):
    stage: str = Field(..., min_length=1, max_length=64)
    scheduled_at: str | None = None  # ISO-8601 (kept as string; freeform for v0.1)


class QIConfirmRequest(BaseModel):
    qualified: bool


async def _insert_outcome(
    *,
    user_id: str,
    application_id: str,
    event: str,
    source: str,
    note: str | None = None,
    ext_message_id: str | None = None,
) -> dict[str, Any]:
    if event not in EVENT_ENUM:
        raise HTTPException(status_code=400, detail={"error": "unknown_event", "allowed": sorted(EVENT_ENUM)})
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "application_id": application_id,
        "event": event,
        "source": source,
        "note": note,
        "ext_message_id": ext_message_id,
        "ts": utc_now(),
    }
    await get_db().outcomes.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.post("/applications/{application_id}/outcomes", status_code=201)
async def log_outcome(
    application_id: str,
    req: LogOutcomeRequest,
    user: dict = Depends(require_consent("track_applications")),
):
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")

    # Append outcome first (append-only ledger — succeed even if state transition below is a no-op).
    outcome = await _insert_outcome(
        user_id=user["id"], application_id=application_id,
        event=req.event, source="manual", note=req.note,
    )

    target_state = EVENT_TO_STATE.get(req.event)
    transition_result: dict | None = None
    transition_error: str | None = None
    if target_state and target_state != app_row["state"]:
        try:
            updated = await atomic_transition(
                user_id=user["id"], application_id=application_id,
                expected_state=app_row["state"], new_state=target_state,
            )
            if updated:
                transition_result = {"from": app_row["state"], "to": target_state}
                app_row = updated
            else:
                transition_error = "state_precondition_failed"
        except InvalidTransition as ie:
            transition_error = "invalid_transition"
            # keep the outcome, expose the reason
            allowed = sorted(ALLOWED_TRANSITIONS.get(app_row["state"], set()))
            await audit.write(user["id"], "outcome.transition_rejected",
                              f"application:{application_id}",
                              {"event": req.event, "from": ie.from_state, "to": ie.to_state,
                               "allowed_from_here": allowed})
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "invalid_transition",
                    "from": ie.from_state,
                    "to": ie.to_state,
                    "allowed_from_here": allowed,
                    "outcome_id": outcome["id"],  # outcome IS persisted (append-only) — surface the id
                },
            )

    await audit.write(user["id"], "outcome.logged", f"application:{application_id}",
                      {"event": req.event, "transition": transition_result, "error": transition_error})
    return {"outcome": outcome, "transition": transition_result, "application_state": app_row["state"]}


@router.get("/applications/{application_id}/outcomes")
async def list_outcomes(application_id: str, user: dict = Depends(get_current_user)):
    cur = get_db().outcomes.find(
        {"user_id": user["id"], "application_id": application_id},
        {"_id": 0},
    ).sort("ts", 1)
    return {"outcomes": [o async for o in cur]}


@router.get("/tracker")
async def get_tracker(user: dict = Depends(require_consent("track_applications"))):
    """Return applications grouped by tracker column + latest outcome per app.

    Columns (founder brief §D): Prepared → Submitted → Response → Interview → Offer → Closed.
    """
    db = get_db()
    apps = [a async for a in db.applications.find({"user_id": user["id"]}, {"_id": 0}).sort("updated_at", -1)]
    # Latest outcome per app in one aggregation
    outcomes = [o async for o in db.outcomes.find({"user_id": user["id"]}, {"_id": 0}).sort("ts", -1)]
    latest_by_app: dict[str, dict] = {}
    for o in outcomes:
        latest_by_app.setdefault(o["application_id"], o)
    interviews_by_app: dict[str, list[dict]] = {}
    async for iv in db.interviews.find({"user_id": user["id"]}, {"_id": 0}).sort("scheduled_at", 1):
        interviews_by_app.setdefault(iv["application_id"], []).append(iv)

    def column_for(state: str) -> str:
        return {
            "shortlisted": "prepared",
            "preparing": "prepared",
            "awaiting_approval": "prepared",
            "approved": "prepared",
            "submitting": "submitted",
            "submitted": "submitted",
            "response": "response",
            "interview": "interview",
            "offer": "offer",
            "closed": "closed",
        }.get(state, "prepared")

    cards: dict[str, list[dict]] = {
        "prepared": [], "submitted": [], "response": [],
        "interview": [], "offer": [], "closed": [],
    }
    for a in apps:
        col = column_for(a["state"])
        cards[col].append({
            "application_id": a["id"],
            "state": a["state"],
            "job_snapshot": a.get("job_snapshot") or {},
            "route": a.get("route"),
            "created_at": a.get("created_at"),
            "updated_at": a.get("updated_at"),
            "is_sample": bool((a.get("job_snapshot") or {}).get("is_sample")),
            "latest_outcome": latest_by_app.get(a["id"]),
            "interviews": interviews_by_app.get(a["id"], []),
        })
    return {"columns": cards, "totals": {k: len(v) for k, v in cards.items()}}


# ---------------------------------------------------------------------- #
# Interviews + Qualified-Interview confirm
# ---------------------------------------------------------------------- #

@router.post("/applications/{application_id}/interviews", status_code=201)
async def schedule_interview(
    application_id: str,
    req: ScheduleInterviewRequest,
    user: dict = Depends(require_consent("track_applications")),
):
    """Schedule an interview + advance the funnel to `interview`.

    Spec (Phase 5 Fix Directive P1): a scheduled interview means the application is at
    the Interview stage. This endpoint:
      1. Inserts the interviews row.
      2. Appends an APPEND-ONLY `interview_scheduled` outcome.
      3. Atomically transitions application.state to `interview` when the current state
         is `submitted` or `response`. Illegal source states are 409 with
         `allowed_from_here` surfaced — the interview row + outcome are STILL persisted
         (append-only ledger) so the user can correct application state manually.
    """
    db = get_db()
    app_row = await db.applications.find_one({"id": application_id, "user_id": user["id"]}, {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")
    now = utc_now()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": application_id,
        "stage": req.stage,
        "scheduled_at": req.scheduled_at,
        "qualified": None,
        "source": "manual",
        "created_at": now,
        "updated_at": now,
    }
    await db.interviews.insert_one(doc)
    await audit.write(user["id"], "interview.scheduled", f"application:{application_id}",
                      {"interview_id": doc["id"], "stage": req.stage})
    doc.pop("_id", None)

    # Append the outcome ledger row (append-only).
    outcome = await _insert_outcome(
        user_id=user["id"], application_id=application_id,
        event="interview_scheduled", source="manual",
        note=f"stage={req.stage}",
    )

    # Advance to `interview` when legal. Interview must come from submitted or response.
    current = app_row["state"]
    transition = None
    transition_error = None
    if current == "interview":
        transition = {"from": current, "to": "interview", "no_op": True}
    elif current in {"submitted", "response"}:
        try:
            updated = await atomic_transition(
                user_id=user["id"], application_id=application_id,
                expected_state=current, new_state="interview",
            )
            if updated:
                transition = {"from": current, "to": "interview"}
                app_row = updated
            else:
                transition_error = "state_precondition_failed"
        except InvalidTransition as ie:
            transition_error = "invalid_transition"
            await audit.write(user["id"], "interview.transition_rejected",
                              f"application:{application_id}",
                              {"from": ie.from_state, "to": ie.to_state})
    else:
        transition_error = "state_source_not_eligible_for_interview"

    return {
        "interview": doc,
        "outcome": outcome,
        "transition": transition,
        "transition_error": transition_error,
        "application_state": app_row["state"],
    }


@router.post("/interviews/{interview_id}/qualified")
async def confirm_qualified_interview(
    interview_id: str,
    req: QIConfirmRequest,
    user: dict = Depends(require_consent("track_applications")),
):
    db = get_db()
    now = utc_now()
    updated = await db.interviews.find_one_and_update(
        {"id": interview_id, "user_id": user["id"]},
        {"$set": {"qualified": bool(req.qualified), "updated_at": now}},
        projection={"_id": 0},
        return_document=True,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="interview_not_found")
    await audit.write(user["id"], "interview.qi_confirm",
                      f"interview:{interview_id}", {"qualified": bool(req.qualified)})
    return updated


# ---------------------------------------------------------------------- #
# Inbound webhook stub (Founder brief §D.3)
# ---------------------------------------------------------------------- #

def forward_address_for(user_id: str) -> dict:
    """User-facing "labeled stub" address. Real parsing lands post-v0.1."""
    short = user_id.replace("-", "")[:10]
    return {
        "address": f"inbound+{short}@opportunityos.example",
        "label": "INBOUND PARSING — labeled stub in v0.1; log updates manually",
    }


@router.get("/tracker/forward-address")
async def read_forward_address(user: dict = Depends(get_current_user)):
    return forward_address_for(user["id"])
