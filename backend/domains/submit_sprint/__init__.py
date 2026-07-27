"""Submit-Sprint (FIXTURE-ONLY) — Phase 4 Founder Brief · Item 3.

Rails:
  * FIXTURE-SCOPED ONLY. The endpoint accepts requests only when the caller
    is the fixture user (email whitelisted in FIXTURE_EMAILS below) OR the
    caller carries the founder-only "sprint_operator" role.
  * NEVER sends anything to a real employer. Sprint slots operate against
    LOCAL FIXTURE JOBS ONLY. Any application whose job is not fixture (e.g.
    company_name != "SampleCo (demo)") is REJECTED with 400.
  * One-keypress confirmation is a UI concern — the backend simply exposes
    a "confirm slot" endpoint that requires a fresh `confirm_token` obtained
    from `POST /start`. Each token is single-use and expires in 5 minutes.
  * Emergency stop: `POST /stop` marks the sprint as `state="halted"` and
    every subsequent /confirm returns 409 sprint_halted.
  * Receipts: every completed slot writes a `submission_receipts` row with
    `kind="fixture_sprint"` and `sent_to_smtp=false`.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.deps import require_consent
from core.db import get_db
from core.time_utils import utc_now
from domains.audit import service as audit
from services import preflight_validator as preflight


router = APIRouter(prefix="/api/v1/sprint", tags=["submit_sprint"])


FIXTURE_EMAILS = {
    "fixture-ead@opportunityos.dev",
    "fixture-admin@opportunityos.dev",
}
FIXTURE_COMPANY_ALLOWLIST = {"sampleco (demo)"}


def _assert_fixture_user(user: dict) -> None:
    email = (user.get("email") or "").lower()
    roles = user.get("roles") or []
    if email in FIXTURE_EMAILS or "sprint_operator" in roles:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
        "error": "sprint_fixture_only",
        "message": "Submit-Sprint is fixture-only. This account is not on the fixture allowlist.",
    })


def _assert_fixture_job(app_row: dict) -> None:
    snap = app_row.get("job_snapshot") or {}
    if snap.get("is_sample") is True:
        return
    company = (snap.get("company_name") or "").lower().strip()
    if company in FIXTURE_COMPANY_ALLOWLIST:
        return
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={
        "error": "sprint_not_fixture_job",
        "message": ("Submit-Sprint only operates on fixture jobs. "
                    "Real employer jobs are never used in sprint mode."),
        "application_id": app_row.get("id"),
        "company_name": snap.get("company_name"),
    })


class StartRequest(BaseModel):
    application_ids: list[str] = Field(min_length=1, max_length=20)


@router.post("/start")
async def start_sprint(req: StartRequest,
                        user: dict = Depends(require_consent("submit_applications"))):
    _assert_fixture_user(user)
    db = get_db()
    apps: list[dict] = []
    async for row in db.applications.find(
        {"id": {"$in": req.application_ids}, "user_id": user["id"]},
        {"_id": 0},
    ):
        _assert_fixture_job(row)
        apps.append(row)
    if len(apps) != len(req.application_ids):
        missing = set(req.application_ids) - {a["id"] for a in apps}
        raise HTTPException(status_code=404, detail={"error": "application_ids_not_found",
                                                       "missing": sorted(missing)})

    sprint_id = str(uuid.uuid4())
    now = utc_now()
    slots = [
        {"slot_id": str(uuid.uuid4()), "application_id": a["id"],
         "job_title": (a.get("job_snapshot") or {}).get("title"),
         "state": "queued",
         "confirm_token": secrets.token_urlsafe(24),
         "confirm_expires_at": now + timedelta(minutes=5)}
        for a in apps
    ]
    doc = {
        "id": sprint_id, "user_id": user["id"], "state": "running",
        "started_at": now, "halted_at": None, "completed_at": None,
        "slots": slots, "completed_slot_count": 0,
    }
    await db.submit_sprints.insert_one(doc)
    await audit.write(user["id"], "sprint.start", f"sprint:{sprint_id}",
                       {"slot_count": len(slots)})
    doc.pop("_id", None)
    return doc


class ConfirmRequest(BaseModel):
    slot_id: str
    confirm_token: str


@router.post("/{sprint_id}/confirm")
async def confirm_slot(sprint_id: str, req: ConfirmRequest,
                        user: dict = Depends(require_consent("submit_applications"))):
    _assert_fixture_user(user)
    db = get_db()
    sprint = await db.submit_sprints.find_one({"id": sprint_id, "user_id": user["id"]},
                                                 {"_id": 0})
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint_not_found")
    if sprint["state"] == "halted":
        raise HTTPException(status_code=409, detail={"error": "sprint_halted"})
    if sprint["state"] == "completed":
        raise HTTPException(status_code=409, detail={"error": "sprint_completed"})

    target = next((s for s in sprint["slots"] if s["slot_id"] == req.slot_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="slot_not_found")
    if target["state"] != "queued":
        raise HTTPException(status_code=409, detail={"error": "slot_not_queued",
                                                       "current_state": target["state"]})
    if target["confirm_token"] != req.confirm_token:
        raise HTTPException(status_code=403, detail={"error": "bad_confirm_token"})
    expiry = target["confirm_expires_at"]
    if isinstance(expiry, str):
        expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expiry:
        raise HTTPException(status_code=409, detail={"error": "confirm_token_expired"})

    now = utc_now()
    # =========================================================
    # PRE-FLIGHT VALIDATOR (Founder Directive · Phase 5.0)
    # ---------------------------------------------------------
    # Sprint is fixture-only, but the validator still runs — no
    # receipt is written unless every resume line traces to an
    # approved Passport claim. A blocked verdict moves the
    # application to review lane with reason
    # `validator_blocked_mismatch`.
    # =========================================================
    verdict = await preflight.preflight_check(
        user_id=user["id"],
        application_id=target["application_id"],
        channel=preflight.CHANNEL_SPRINT_FIXTURE,
        outbound_fields=None,  # sprint has no outbound fields
    )
    if not verdict.ok:
        await preflight.block_and_route_to_review(verdict, audit_actor=user["id"])
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": preflight.REASON_TOP_LEVEL,
                    "verdict": verdict.compact(),
                    "reasons": verdict.reasons,
                    "message": "Sprint confirm blocked by pre-flight "
                                "validator. Application moved to review lane."},
        )
    await preflight.persist_verdict(verdict)

    # Write a fixture-sprint receipt. Application STATE is NOT flipped to
    # 'submitted' — we're a fixture harness, not a real submitter.
    #
    # We populate `company_id` and `req_ref` with deterministic values so
    # the compound unique index `(user_id, company_id, req_ref)` on
    # `submission_receipts` cannot collide across sprint slots, and cannot
    # collide with an email-route dispatch for the same user. Empirically-
    # verified 2026-07-28 (independent tester): writing null for either
    # field triggers pymongo DuplicateKeyError E11000 on the second row
    # because MongoDB treats nulls as equal in a compound unique index.
    _snap = (await db.applications.find_one(
        {"id": target["application_id"], "user_id": user["id"]},
        {"_id": 0, "job_snapshot": 1, "company_id": 1, "job_id": 1},
    )) or {}
    _js = _snap.get("job_snapshot") or {}
    _company_id = (
        _snap.get("company_id")
        or _js.get("company_id")
        or ((_js.get("canonical_key") or "").split("::")[0] or None)
        or "sampleco.demo"
    )
    _job_id = _snap.get("job_id") or target["application_id"]
    receipt = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": target["application_id"],
        "job_id": _job_id,
        "company_id": _company_id,
        # Unique per slot ⇒ no compound-index collision even if the same
        # user runs multiple sprints against the same fixture company.
        "req_ref": f"sprint:slot:{req.slot_id}",
        "materials_manifest_hash": f"sprint_fixture:{req.slot_id}",
        "submit_channel": "sprint_fixture",
        "supersedes": None,
        "ts": now,
        "route": "sprint_fixture",
        "kind": "fixture_sprint",
        "sprint_id": sprint_id,
        "slot_id": req.slot_id,
        "sent_to_smtp": False,
        "created_at": now,
        # Pre-flight verdict embedded on the receipt (Founder Directive
        # Phase 5.0). `ok=True` by construction — a blocked verdict
        # would have raised HTTP 422 above and no receipt is written.
        "validator_verdict": verdict.compact(),
    }
    await db.submission_receipts.insert_one(receipt)

    # Mark slot complete atomically
    updated = await db.submit_sprints.find_one_and_update(
        {"id": sprint_id, "user_id": user["id"], "slots.slot_id": req.slot_id,
         "slots.state": "queued"},
        {"$set": {"slots.$.state": "completed",
                    "slots.$.completed_at": now,
                    "slots.$.receipt_id": receipt["id"]},
         "$inc": {"completed_slot_count": 1}},
        return_document=True, projection={"_id": 0},
    )
    # If all slots complete, mark sprint completed
    if updated and updated["completed_slot_count"] >= len(updated["slots"]):
        await db.submit_sprints.update_one(
            {"id": sprint_id, "user_id": user["id"]},
            {"$set": {"state": "completed", "completed_at": now}},
        )
    await audit.write(user["id"], "sprint.confirm_slot",
                       f"sprint:{sprint_id}/slot:{req.slot_id}",
                       {"receipt_id": receipt["id"]})
    return {"ok": True, "receipt_id": receipt["id"], "sprint": updated}


@router.post("/{sprint_id}/stop")
async def stop_sprint(sprint_id: str,
                       user: dict = Depends(require_consent("submit_applications"))):
    _assert_fixture_user(user)
    db = get_db()
    row = await db.submit_sprints.find_one_and_update(
        {"id": sprint_id, "user_id": user["id"], "state": "running"},
        {"$set": {"state": "halted", "halted_at": utc_now()}},
        return_document=True, projection={"_id": 0},
    )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "sprint_not_running_or_missing"})
    await audit.write(user["id"], "sprint.stop", f"sprint:{sprint_id}", {})
    return row


@router.get("/{sprint_id}")
async def get_sprint(sprint_id: str,
                      user: dict = Depends(require_consent("submit_applications"))):
    _assert_fixture_user(user)
    row = await get_db().submit_sprints.find_one({"id": sprint_id, "user_id": user["id"]},
                                                    {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="sprint_not_found")
    return row


@router.get("")
async def list_mine(user: dict = Depends(require_consent("submit_applications"))):
    _assert_fixture_user(user)
    rows: list[dict] = []
    async for r in get_db().submit_sprints.find({"user_id": user["id"]},
                                                   {"_id": 0}).sort("started_at", -1).limit(50):
        rows.append(r)
    return {"sprints": rows, "total": len(rows)}
