"""Email-route executor — local-sink dry-run (Phase 4 Founder Brief · Item 5).

Rails:
  * Preview only. Never hits SMTP or an external provider.
  * Rendered messages are persisted to `email_outbox` in state="dry_run"
    (never "sent"). A dedicated `sent_to_smtp: false` flag makes the
    non-transport visible in the payload.
  * Idempotency: dedup by sha256(user_id + app_id + destination). Repeat
    dispatches for the same tuple return the SAME outbox_id with a
    `duplicate=true` flag.
  * Throttles: at most 10 dispatches per user per hour and 3 per hour per
    destination.
  * Receipts: one submission_receipt per dispatched application_id (route
    tag = "email"; NEVER "submitted" in preview — always "prepared").
  * Consent-gated on `submit_applications` (same scope real submit will use).

Config (documented in /app/docs/EMAIL-ROUTE-CONFIG.md — NOT set in preview):
    EMAIL_ROUTE_PROVIDER   (resend | sendgrid | smtp)
    EMAIL_ROUTE_FROM       (from address; must be on a domain with valid
                              SPF + DKIM records; see docs)
    EMAIL_ROUTE_API_KEY    (provider API key; user must supply)
    EMAIL_ROUTE_DRY_RUN    (default "true" — flipping to "false" is a
                              founder-only action gated behind explicit
                              env change, never a runtime flag)
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.deps import require_consent
from core.db import get_db
from core.time_utils import utc_now
from domains.audit import service as audit
from services import preflight_validator as preflight


router = APIRouter(prefix="/api/v1/email-route", tags=["email_route"])


THROTTLE_PER_USER_PER_HOUR = 10
THROTTLE_PER_DEST_PER_HOUR = 3


class EmailDispatchRequest(BaseModel):
    application_id: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=3, max_length=200)  # RFC 5321-ish
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    reply_to: str | None = Field(default=None, max_length=200)


def _dedup_key(user_id: str, application_id: str, destination: str) -> str:
    payload = f"{user_id}::{application_id}::{destination.lower().strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _throttle_check(user_id: str, destination: str) -> None:
    db = get_db()
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    user_n = await db.email_outbox.count_documents({"user_id": user_id,
                                                      "created_at": {"$gte": since}})
    if user_n >= THROTTLE_PER_USER_PER_HOUR:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={
            "error": "email_route_user_throttled",
            "window_hours": 1, "cap": THROTTLE_PER_USER_PER_HOUR,
            "message": f"You've hit the {THROTTLE_PER_USER_PER_HOUR}/hour user cap.",
        })
    dest_n = await db.email_outbox.count_documents({"destination": destination.lower(),
                                                      "created_at": {"$gte": since}})
    if dest_n >= THROTTLE_PER_DEST_PER_HOUR:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={
            "error": "email_route_dest_throttled",
            "window_hours": 1, "cap": THROTTLE_PER_DEST_PER_HOUR,
            "message": f"Destination {destination} has hit the {THROTTLE_PER_DEST_PER_HOUR}/hour cap.",
        })


async def _load_booking_url(user_id: str) -> str | None:
    """Phase 1 §vi (1c) — read the user's most-recent saved `booking_url`
    from their preferences payload. Returns None if not set or if the
    stored value is empty. Validation on save already asserts https://.
    """
    row = await get_db().preferences.find_one(
        {"user_id": user_id}, sort=[("version", -1)],
        projection={"_id": 0, "payload": 1},
    )
    url = ((row or {}).get("payload") or {}).get("booking_url")
    if not url:
        return None
    url = str(url).strip()
    return url or None


@router.post("/dispatch", status_code=status.HTTP_201_CREATED)
async def dispatch(req: EmailDispatchRequest,
                    user: dict = Depends(require_consent("submit_applications"))):
    db = get_db()
    # Ownership check
    app_row = await db.applications.find_one({"id": req.application_id,
                                                "user_id": user["id"]},
                                               {"_id": 0})
    if not app_row:
        raise HTTPException(status_code=404, detail="application_not_found")

    dedup = _dedup_key(user["id"], req.application_id, req.destination)
    existing = await db.email_outbox.find_one({"dedup_key": dedup}, {"_id": 0})
    if existing:
        return {**existing, "duplicate": True, "sent_to_smtp": False}

    await _throttle_check(user["id"], req.destination.lower())

    # =========================================================
    # PRE-FLIGHT VALIDATOR (Founder Directive · Phase 5.0)
    # ---------------------------------------------------------
    # NO code path below this line writes any outbound / receipt
    # state until the pre-flight validator returns ok=True. Every
    # outbound field and every resume line is machine-diffed
    # against the approved Passport claim it traces to; a
    # mismatch or untraceable line blocks and routes to the
    # review lane with reason `validator_blocked_mismatch`.
    # =========================================================
    verdict = await preflight.preflight_check(
        user_id=user["id"],
        application_id=req.application_id,
        channel=preflight.CHANNEL_EMAIL_DRY_RUN,
        outbound_fields={
            "destination": req.destination,
            "subject": req.subject,
            "body": req.body,
        },
    )
    if not verdict.ok:
        await preflight.block_and_route_to_review(verdict, audit_actor=user["id"])
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": preflight.REASON_TOP_LEVEL,
                    "verdict": verdict.compact(),
                    "reasons": verdict.reasons,
                    "message": "Dispatch blocked by pre-flight validator. "
                                "Application moved to review lane; see the "
                                "verdict for the specific untraceable / "
                                "mismatched item."},
        )
    # Persist the passing verdict too (audit trail — every dispatch has
    # a stored verdict, not just blocks).
    await preflight.persist_verdict(verdict)

    # Phase 1 §vi (1c) — instant-scheduling link. Append the user's saved
    # booking URL to the outbound body when present. Runs AFTER preflight
    # so validator claim-grounding is not muddied by user-supplied contact
    # metadata (a URL is not a claim). Never invents placement — the line
    # is appended verbatim as a signature-adjacent footer.
    body_final = req.body
    booking_url = await _load_booking_url(user["id"])
    if booking_url:
        body_final = f"{req.body.rstrip()}\n\nBook a time: {booking_url}"

    now = utc_now()
    outbox = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": req.application_id,
        "destination": req.destination.lower(),
        "subject": req.subject,
        "body": body_final,
        "reply_to": req.reply_to,
        "dedup_key": dedup,
        "state": "dry_run",
        "sent_to_smtp": False,
        "booking_url_attached": bool(booking_url),
        "created_at": now,
        "provider": "local_sink",
    }
    await db.email_outbox.insert_one(outbox)

    # Receipt — records the dispatch attempt but does NOT flip application
    # state to submitted in preview (that happens only when the real route
    # is enabled behind an explicit env change).
    #
    # We populate `company_id` and `req_ref` with deterministic values so
    # the compound unique index `(user_id, company_id, req_ref)` on
    # `submission_receipts` cannot collide with a prior sprint receipt or
    # a prior email-route dispatch by the same user. Empirically-verified
    # 2026-07-28: writing null for either field triggers pymongo
    # DuplicateKeyError E11000 because MongoDB treats nulls as equal in
    # a compound unique index.
    _js = (app_row.get("job_snapshot") or {})
    _company_id = (
        app_row.get("company_id")
        or _js.get("company_id")
        or ((_js.get("canonical_key") or "").split("::")[0] or None)
        # Deterministic sentinel — unique per outbox row so no two email
        # receipts can ever share (user, company_id, req_ref).
        or f"email-route:{outbox['id']}"
    )
    _job_id = app_row.get("job_id") or req.application_id
    receipt = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": req.application_id,
        "job_id": _job_id,
        "company_id": _company_id,
        # Unique per outbox row ⇒ no compound-index collision.
        "req_ref": f"email-route:outbox:{outbox['id']}",
        "materials_manifest_hash": f"email_dry_run:{dedup}",
        "submit_channel": "email_dry_run",
        "supersedes": None,
        "ts": now,
        "route": "email",
        "kind": "email_dry_run",
        "outbox_id": outbox["id"],
        "destination": req.destination.lower(),
        "created_at": now,
        # Pre-flight verdict is embedded so the receipt itself is proof
        # that the dispatch cleared the chokepoint (Founder Directive
        # Phase 5.0). `ok=True` by construction here — an `ok=False`
        # verdict would have raised HTTP 422 above.
        "validator_verdict": verdict.compact(),
    }
    await db.submission_receipts.insert_one(receipt)

    await audit.write(user["id"], "email_route.dispatch",
                       f"outbox:{outbox['id']}",
                       {"application_id": req.application_id,
                        "destination": req.destination.lower(),
                        "sent_to_smtp": False})

    outbox.pop("_id", None)
    return {**outbox, "duplicate": False, "receipt_id": receipt["id"]}


@router.get("/outbox")
async def list_outbox(user: dict = Depends(require_consent("submit_applications"))):
    rows: list[dict] = []
    async for r in get_db().email_outbox.find({"user_id": user["id"]},
                                                {"_id": 0}).sort("created_at", -1).limit(100):
        rows.append(r)
    return {"outbox": rows, "total": len(rows)}


@router.get("/outbox/{outbox_id}")
async def get_outbox_row(outbox_id: str,
                          user: dict = Depends(require_consent("submit_applications"))):
    row = await get_db().email_outbox.find_one({"id": outbox_id, "user_id": user["id"]},
                                                  {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="outbox_row_not_found")
    return row
