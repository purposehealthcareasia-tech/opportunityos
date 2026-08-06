"""Phase 1 §vii (1d) — Follow-up engine (drafts only, never auto-sent).

RULE (Founder directive 2026-08-06):
  Draft a follow-up per submitted application, timed off the employer's
  median response window (fallback 7 days). Enqueue to `follow_up_drafts`
  in `state="draft"`. The drafts collection is REVIEW-ONLY.

  HARD INVARIANT (test-locked): NO code path may move a draft toward
  sending except an explicit manual review action, which creates a
  FRESH `email_outbox` record (itself still dry-run). No sweep, cron,
  scheduler, or "auto-send if pass X hours" is permitted. See
  `backend/tests/test_phase1_follow_ups.py::test_no_dispatch_sweep_touches_drafts`.

  Approval flow:
    (1) draft is inserted with `state="draft"`, `body_preview`, and
        `scheduled_for`.
    (2) user reviews the draft — sees full body + suggested send date.
    (3) user hits POST /follow-ups/{id}/approve → creates a fresh
        `email_outbox` row (via `email_route.dispatch` under the hood)
        and marks the draft `state="approved_and_dispatched"`.
    (4) alternatively POST /follow-ups/{id}/discard →
        `state="discarded"`.

  Consent gate: `submit_applications` (Phase 4 dispatch-authorization
  scope). This is a dispatch-adjacent surface and must never bypass
  the consent that authorizes real submissions.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.db import get_db
from core.deps import require_consent
from core.time_utils import utc_now
from domains.audit import service as audit
from services import outcome_autopilot as _oa


router = APIRouter(prefix="/api/v1/follow-ups", tags=["follow-ups"])


# ------------------------------ Constants -------------------------------- #

DEFAULT_FALLBACK_DAYS = 7
STATE_DRAFT = "draft"
STATE_APPROVED = "approved_and_dispatched"
STATE_DISCARDED = "discarded"
_ALL_STATES = {STATE_DRAFT, STATE_APPROVED, STATE_DISCARDED}


# ------------------------------ Models ----------------------------------- #

class DraftFollowUpRequest(BaseModel):
    """Optional per-app tuning when the caller wants to override defaults."""
    application_id: str
    tone: Optional[str] = Field(default="warm",
                                  pattern="^(warm|concise|inquisitive)$")
    custom_note: Optional[str] = Field(default=None, max_length=1000)


class ApproveFollowUpRequest(BaseModel):
    destination: str = Field(min_length=3, max_length=200,
                                description="Recipient email. Uses email-route dispatch (dry-run).")
    subject: str = Field(min_length=1, max_length=300)


# ------------------------------ Helpers ---------------------------------- #

def _tone_prelude(tone: str) -> str:
    if tone == "concise":
        return "Following up on my application for {title} at {employer}."
    if tone == "inquisitive":
        return "Wanted to check in on my application for {title} at {employer} and see whether the timing is still open."
    # warm (default)
    return "Circling back on my application for {title} at {employer} — I remain very interested."


async def _employer_median_days(user_id: str, employer: str) -> Optional[float]:
    """Return the user's own median days-to-response for this employer
    (from application_outcomes). None if no data. USER-SCOPED — no cross-
    user response history is read."""
    try:
        stats = await _oa.compute_group_stats(user_id, since_days=90,
                                                 group_by="employer")
    except Exception:
        return None
    row = stats.get(employer or "") or {}
    md = row.get("median_days_to_response")
    return md if isinstance(md, (int, float)) else None


async def _load_application(user_id: str, application_id: str) -> dict:
    row = await get_db().applications.find_one(
        {"id": application_id, "user_id": user_id}, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="application_not_found")
    return row


def _build_body(app: dict, tone: str, custom_note: Optional[str]) -> str:
    js = app.get("job_snapshot") or {}
    employer = js.get("company_name") or "the team"
    title = js.get("title") or "the role"
    prelude = _tone_prelude(tone).format(title=title, employer=employer)
    lines = [
        prelude,
        "",
        "If there's anything I can add — writing samples, references, availability — happy to send it over.",
    ]
    if custom_note and custom_note.strip():
        lines.extend(["", custom_note.strip()])
    lines.extend(["", "Thanks for your time."])
    return "\n".join(lines)


# ------------------------------ Endpoints -------------------------------- #

@router.post("", status_code=201)
async def create_draft(req: DraftFollowUpRequest,
                          user: dict = Depends(require_consent("submit_applications"))):
    """Draft (do NOT send) a follow-up for one application.

    Timing rule:
      * If the user has an observed median days-to-response for this
        employer, `scheduled_for = submitted_at + median_days`.
      * Otherwise fallback = submitted_at + 7 days (DEFAULT_FALLBACK_DAYS).
      * If submitted_at is missing, fallback from application.created_at.
    """
    app_row = await _load_application(user["id"], req.application_id)
    submitted_at = app_row.get("submitted_at") or app_row.get("created_at")
    if submitted_at is None:
        submitted_at = datetime.now(timezone.utc)
    if submitted_at.tzinfo is None:
        submitted_at = submitted_at.replace(tzinfo=timezone.utc)
    js = app_row.get("job_snapshot") or {}
    employer = (app_row.get("company_id") or js.get("company_id")
                 or (js.get("canonical_key") or "").split("::")[0])
    median = await _employer_median_days(user["id"], employer or "")
    days_used = median if median is not None else DEFAULT_FALLBACK_DAYS
    scheduled_for = submitted_at + timedelta(days=days_used)

    body = _build_body(app_row, req.tone or "warm", req.custom_note)
    draft = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": req.application_id,
        "employer": employer,
        "state": STATE_DRAFT,
        "tone": req.tone or "warm",
        "custom_note": req.custom_note,
        "body_preview": body,
        "median_days_source": ("employer" if median is not None else "fallback_7d"),
        "days_used": days_used,
        "scheduled_for": scheduled_for,
        "created_at": utc_now(),
    }
    await get_db().follow_up_drafts.insert_one(dict(draft))
    await audit.write(user["id"], "follow_up.draft", f"follow_up:{draft['id']}",
                        {"application_id": req.application_id,
                          "days_used": days_used,
                          "median_source": draft["median_days_source"]})
    return {**draft, "_hard_invariant": "drafts are never auto-sent; approve creates fresh email_outbox"}


@router.get("")
async def list_drafts(state: Optional[str] = None,
                        user: dict = Depends(require_consent("submit_applications"))):
    """List follow-up drafts for the current user, most recent first."""
    q: dict = {"user_id": user["id"]}
    if state:
        if state not in _ALL_STATES:
            raise HTTPException(status_code=400, detail={"error": "invalid_state",
                                                            "allowed": sorted(_ALL_STATES)})
        q["state"] = state
    rows = []
    async for r in get_db().follow_up_drafts.find(q, {"_id": 0}).sort("scheduled_for", 1):
        rows.append(r)
    return {"drafts": rows}


@router.post("/{draft_id}/approve", status_code=201)
async def approve_draft(draft_id: str, req: ApproveFollowUpRequest,
                          user: dict = Depends(require_consent("submit_applications"))):
    """Approve a draft — creates a FRESH email_outbox row via the existing
    email-route dispatch pipeline (which itself is dry-run in preview).
    The draft moves to `state=approved_and_dispatched` with a pointer to
    the outbox row it created.

    HARD INVARIANT: this is the ONLY endpoint that may move a draft toward
    sending. No sweep, cron, scheduler, or timer touches drafts.
    """
    db = get_db()
    draft = await db.follow_up_drafts.find_one(
        {"id": draft_id, "user_id": user["id"]}, {"_id": 0})
    if not draft:
        raise HTTPException(status_code=404, detail="follow_up_not_found")
    if draft["state"] != STATE_DRAFT:
        raise HTTPException(status_code=409, detail={
            "error": "follow_up_not_in_draft_state",
            "current_state": draft["state"],
        })

    # Delegate to email-route dispatch. It runs pre-flight validator,
    # enforces email throttles, appends booking_url (§vi), inserts a
    # fresh email_outbox row, and writes a submission receipt. Everything
    # remains DRY-RUN in preview (state="dry_run" on the outbox).
    from domains.email_route import EmailDispatchRequest, dispatch as _dispatch
    dispatch_req = EmailDispatchRequest(
        application_id=draft["application_id"],
        destination=req.destination,
        subject=req.subject,
        body=draft["body_preview"],
        reply_to=None,
    )
    dispatch_result = await _dispatch(dispatch_req, user=user)  # type: ignore[arg-type]

    await db.follow_up_drafts.update_one(
        {"id": draft_id, "user_id": user["id"]},
        {"$set": {
            "state": STATE_APPROVED,
            "approved_at": utc_now(),
            "email_outbox_id": (dispatch_result.get("id") if isinstance(dispatch_result, dict) else None),
        }},
    )
    await audit.write(user["id"], "follow_up.approve", f"follow_up:{draft_id}", {
        "email_outbox_id": (dispatch_result.get("id") if isinstance(dispatch_result, dict) else None),
    })
    return {"id": draft_id, "state": STATE_APPROVED,
             "dispatch": dispatch_result}


@router.post("/{draft_id}/discard", status_code=200)
async def discard_draft(draft_id: str,
                          user: dict = Depends(require_consent("submit_applications"))):
    """Discard a draft. Idempotent — no error if already discarded."""
    db = get_db()
    draft = await db.follow_up_drafts.find_one(
        {"id": draft_id, "user_id": user["id"]}, {"_id": 0})
    if not draft:
        raise HTTPException(status_code=404, detail="follow_up_not_found")
    if draft["state"] == STATE_DRAFT:
        await db.follow_up_drafts.update_one(
            {"id": draft_id, "user_id": user["id"]},
            {"$set": {"state": STATE_DISCARDED, "discarded_at": utc_now()}},
        )
        await audit.write(user["id"], "follow_up.discard", f"follow_up:{draft_id}", {})
    return {"id": draft_id, "state": STATE_DISCARDED}
