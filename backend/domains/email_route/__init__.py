"""Email-route executor — dry-run by default, real send behind flag.

Rails:
  * DEFAULT: preview / dry-run. Rendered messages persist to
    `email_outbox` with state="dry_run", provider="local_sink",
    sent_to_smtp=False. A dedicated `sent_to_smtp` flag makes the
    non-transport visible in the payload.
  * LIVE: when env `EMAIL_ROUTE_DRY_RUN` is explicitly the string
    `"false"` AND the requested provider is configured & reachable,
    the dispatch calls `provider.send(...)` and records state="sent",
    provider=<slug>, sent_to_smtp=True, provider_message_id=<id>. The
    outbox row + submission_receipt are otherwise identical. Everything
    ELSE (preflight, consent, throttles, dedup, receipt, audit) is
    UNCHANGED between dry-run and live — the flag is transport-only.
  * Idempotency: dedup by sha256(user_id + app_id + destination).
    Repeat dispatches for the same tuple return the SAME outbox_id.
  * Throttles: at most 10 dispatches per user per hour and 3 per hour
    per destination — enforced regardless of dry-run/live.
  * Receipts: one submission_receipt per dispatched application_id.
  * Consent-gated on `submit_applications`.
  * PARKED-DRY-RUN INVARIANT: outbox rows that were written under
    dry-run stay dry-run FOREVER. No sweep, no scheduler, no code
    path replays them on a flag flip. Pinned by
    `tests/test_email_route_live_flip.py::test_parked_dry_run_not_replayed`.

Env vars (documented in /app/docs/EMAIL-ROUTE-CONFIG.md):
    EMAIL_ROUTE_DRY_RUN    ("true" | "false"; missing == "true").
                              Read at dispatch-time via `os.environ.get`,
                              so the runtime read is testable — but the
                              deploy platform still requires RE-PUBLISH
                              to change the value into the worker.
    EMAIL_ROUTE_PROVIDER   ("resend" | "sendgrid"; default "resend").
                              Selects which registered adapter to call
                              in live mode. Never used in dry-run.
    RESEND_API_KEY,        Provider credentials — read AT IMPORT-TIME
    RESEND_FROM_EMAIL,     by the provider adapter's `configure()`
    RESEND_WEBHOOK_SECRET  method (`integrations/email/resend_provider.py`).
                              Changing them REQUIRES RE-PUBLISH.

Self-test path:
    POST /api/v1/email-route/self-test  (owner-emails only).
    Sends a canned message to the caller's own authenticated email.
    Never touches application state; receipt tagged
    kind="email_self_test" so it's distinguishable in audit.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.deps import require_consent, get_current_user
from core.db import get_db
from core.time_utils import utc_now
from domains.audit import service as audit
from services import preflight_validator as preflight
from integrations import registry as integrations_registry
from integrations.base import ProviderError


log = logging.getLogger("oppos.email_route")

router = APIRouter(prefix="/api/v1/email-route", tags=["email_route"])


THROTTLE_PER_USER_PER_HOUR = 10
THROTTLE_PER_DEST_PER_HOUR = 3


def _dispatch_mode() -> str:
    """Return "live" iff EMAIL_ROUTE_DRY_RUN is explicitly the exact
    string "false"; every other value (including unset / typos / caps)
    falls through to "dry_run". Read at dispatch-time so pytest can
    toggle via monkeypatch."""
    raw = os.environ.get("EMAIL_ROUTE_DRY_RUN", "true")
    return "live" if raw == "false" else "dry_run"


def _selected_provider_slug() -> str:
    """Return the provider slug to use when live. Only "resend" and
    "sendgrid" are supported today; any other value falls back to
    "resend" (log a warning)."""
    slug = (os.environ.get("EMAIL_ROUTE_PROVIDER", "resend") or "resend").lower()
    if slug not in ("resend", "sendgrid"):
        log.warning("EMAIL_ROUTE_PROVIDER=%r unsupported, falling back to 'resend'", slug)
        slug = "resend"
    return slug


def _is_owner(user: dict) -> bool:
    """Owner-emails gate — same pattern as
    `domains/discovery/scheduler.py:_is_admin_or_owner`. Admin/support
    roles ALSO pass. Env `PRIVATE_AUTOPILOT_OWNER_EMAILS` is a CSV of
    lowercased emails — read at call-time (safe hot-reload semantics
    on redeploy, no import capture)."""
    if not user:
        return False
    if user.get("role") in ("admin", "support"):
        return True
    email = (user.get("email") or "").lower()
    csv = os.environ.get("PRIVATE_AUTOPILOT_OWNER_EMAILS", "")
    owners = {e.strip().lower() for e in csv.split(",") if e.strip()}
    return email in owners


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

    # ------------------------------------------------------------
    # Phase 6d — Application Credits: check-and-debit the caller's
    # ledger BEFORE any transport-side effect. Runs AFTER preflight /
    # consent / throttle / dedup so credits are a FINAL brake, never
    # a bypass. On insufficient_credits we halt honestly (HTTP 402 +
    # `paused_no_credits`) — the application stays queued (shortlist
    # row is untouched), so refilling later + re-dispatching re-runs
    # the full validation chain (caps/dedup/gates/preflight) — a
    # parked item is re-validated at resume, never dispatched on
    # stale checks.
    # ------------------------------------------------------------
    from domains.credits import service as credits_svc
    # Precompute the receipt_id so debit-idempotency is keyed against
    # the SAME receipt we're about to write below. If the send races
    # or the caller replays, only one debit lands.
    receipt_id_precomputed = str(uuid.uuid4())
    debit = await credits_svc.check_and_debit(
        user_id=user["id"], receipt_id=receipt_id_precomputed,
        application_id=req.application_id, reason="email_route_dispatch",
    )
    if not debit.get("ok"):
        # Log the honest halt (audit but not a receipt — no send happened).
        await audit.write(user["id"], "email_route.halt_no_credits",
                           f"application:{req.application_id}",
                           {"destination": req.destination.lower(),
                            "balance_after": debit.get("balance_after", 0)})
        raise HTTPException(
            status_code=402,
            detail={
                "error": "insufficient_credits",
                "state": "paused_no_credits",
                "balance": debit.get("balance_after", 0),
                "message": "Out of application credits. Item stays queued "
                            "in your shortlist. Grant refills automatically "
                            "on UTC month-start; admin grants also work. "
                            "Re-dispatch to resume — full gates re-run at "
                            "that time.",
            },
        )

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
    # ------------------------------------------------------------
    # DRY-RUN / LIVE fork. This is the ONLY code path where the
    # flag matters — every preflight, throttle, dedup, consent and
    # receipt check above runs unchanged in both modes.
    # ------------------------------------------------------------
    mode = _dispatch_mode()
    outbox_provider = "local_sink"
    outbox_state = "dry_run"
    sent_to_smtp = False
    provider_message_id: str | None = None
    live_send_error: str | None = None

    if mode == "live":
        slug = _selected_provider_slug()
        provider = integrations_registry.get(slug)
        if provider is None:
            live_send_error = f"provider_not_registered:{slug}"
        elif not provider.validate_configuration().ok:
            live_send_error = f"provider_configuration_required:{slug}"
        else:
            try:
                # Use plaintext body → both text/ and html/ so receivers
                # without HTML render cleanly. Escape into a <pre>-safe
                # HTML wrapper (Resend's `html` field is required to be
                # HTML; providing plain text as HTML strips newlines).
                html_body = "<pre style=\"font-family:inherit;white-space:pre-wrap;\">" + \
                    body_final.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + \
                    "</pre>"
                send_result = await provider.send(
                    to=req.destination.lower(),
                    subject=req.subject,
                    html=html_body,
                    text=body_final,
                    metadata={
                        "fynd-application-id": req.application_id,
                        "fynd-user-id": user["id"],
                    },
                )
                # Resend returns {"id": "..."}, SendGrid uses X-Message-Id header
                provider_message_id = (send_result or {}).get("id") or (send_result or {}).get("message_id")
                outbox_provider = slug
                outbox_state = "sent"
                sent_to_smtp = True
            except ProviderError as e:
                live_send_error = f"send_failed:{e.code}"
                log.warning("email_route live-send failed: %s", live_send_error)
            except Exception as e:  # noqa: BLE001 — narrow-log unexpected
                live_send_error = f"send_error:{type(e).__name__}"
                log.exception("email_route unexpected live-send error")

        # SAFETY: if the live path failed for any reason, the outbox
        # row still records honestly as dry-run (never claim "sent"
        # when the provider didn't confirm). The caller sees an
        # explicit `live_send_error` field so retries can be
        # surfaced upstream.

    outbox = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": req.application_id,
        "destination": req.destination.lower(),
        "subject": req.subject,
        "body": body_final,
        "reply_to": req.reply_to,
        "dedup_key": dedup,
        "state": outbox_state,
        "sent_to_smtp": sent_to_smtp,
        "booking_url_attached": bool(booking_url),
        "created_at": now,
        "provider": outbox_provider,
        "provider_message_id": provider_message_id,
        "live_send_error": live_send_error,
        "dispatch_mode": mode,
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
    # Receipt fields track live vs dry-run honestly. `submit_channel`
    # and `kind` follow the dispatch mode so downstream reporting can
    # partition real sends from parked local-sink rows.
    _channel = preflight.CHANNEL_EMAIL_LIVE if outbox_state == "sent" else preflight.CHANNEL_EMAIL_DRY_RUN
    _kind = "email_sent" if outbox_state == "sent" else "email_dry_run"
    _manifest = f"{_kind}:{dedup}"
    receipt = {
        "id": receipt_id_precomputed,   # debit already keyed against this id
        "user_id": user["id"],
        "application_id": req.application_id,
        "job_id": _job_id,
        "company_id": _company_id,
        # Unique per outbox row ⇒ no compound-index collision.
        "req_ref": f"email-route:outbox:{outbox['id']}",
        "materials_manifest_hash": _manifest,
        "submit_channel": _channel,
        "supersedes": None,
        "ts": now,
        "route": "email",
        "kind": _kind,
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
                        "dispatch_mode": mode,
                        "sent_to_smtp": sent_to_smtp,
                        "provider": outbox_provider,
                        "live_send_error": live_send_error})

    outbox.pop("_id", None)
    return {**outbox, "duplicate": False, "receipt_id": receipt["id"]}


# ---------------------------------------------------------------------------
# Owner-only self-test endpoint (added 2026-08-12 with the go-live wiring).
# Sends a canned message to the caller's own authenticated email. Never
# touches application state. Receipt tagged `kind="email_self_test"` so
# it's easily distinguished in audit / dashboards.
# ---------------------------------------------------------------------------
class SelfTestRequest(BaseModel):
    destination: str = Field(min_length=3, max_length=200)


@router.post("/self-test", status_code=status.HTTP_201_CREATED)
async def self_test(req: SelfTestRequest,
                     user: dict = Depends(get_current_user)):
    """First-live-send verification path.

    Requires: owner/admin/support role AND the destination match the
    caller's authenticated email exactly. Sends ONLY when
    EMAIL_ROUTE_DRY_RUN=false AND the Resend/SendGrid provider is
    configured — otherwise records a dry-run outbox row so the flow is
    testable without side effects.
    """
    if not _is_owner(user):
        raise HTTPException(status_code=403, detail={"error": "owner_only"})
    dest = req.destination.strip().lower()
    if dest != (user.get("email") or "").strip().lower():
        raise HTTPException(status_code=400, detail={
            "error": "self_test_destination_mismatch",
            "message": "destination must match the caller's authenticated email exactly.",
        })

    mode = _dispatch_mode()
    outbox_provider = "local_sink"
    outbox_state = "dry_run"
    sent_to_smtp = False
    provider_message_id: str | None = None
    live_send_error: str | None = None
    now = utc_now()
    subject = "[Fynd self-test] Resend live-path verification"
    body = (
        f"This is a self-test message dispatched via the Fynd email route "
        f"on {now.isoformat()}. If you're seeing this in your inbox, the "
        f"live provider path is wired. Recipient: {dest}. Mode at "
        f"dispatch time: {mode}."
    )

    if mode == "live":
        slug = _selected_provider_slug()
        provider = integrations_registry.get(slug)
        if provider is None:
            live_send_error = f"provider_not_registered:{slug}"
        elif not provider.validate_configuration().ok:
            live_send_error = f"provider_configuration_required:{slug}"
        else:
            try:
                html_body = (
                    "<pre style=\"font-family:inherit;white-space:pre-wrap;\">"
                    + body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    + "</pre>"
                )
                res = await provider.send(
                    to=dest, subject=subject, html=html_body, text=body,
                    metadata={"fynd-self-test": "true", "fynd-user-id": user["id"]},
                )
                provider_message_id = (res or {}).get("id") or (res or {}).get("message_id")
                outbox_provider = slug
                outbox_state = "sent"
                sent_to_smtp = True
            except ProviderError as e:
                live_send_error = f"send_failed:{e.code}"
            except Exception as e:  # noqa: BLE001
                live_send_error = f"send_error:{type(e).__name__}"
                log.exception("self-test unexpected live-send error")

    row = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "application_id": None,               # SELF-TEST — never bound to an app
        "destination": dest,
        "subject": subject,
        "body": body,
        "reply_to": None,
        "dedup_key": None,                    # SELF-TEST — not part of dedup surface
        "state": outbox_state,
        "sent_to_smtp": sent_to_smtp,
        "booking_url_attached": False,
        "created_at": now,
        "provider": outbox_provider,
        "provider_message_id": provider_message_id,
        "live_send_error": live_send_error,
        "dispatch_mode": mode,
        "kind": "email_self_test",
    }
    await get_db().email_outbox.insert_one(row)
    await audit.write(user["id"], "email_route.self_test",
                       f"outbox:{row['id']}",
                       {"dispatch_mode": mode,
                        "sent_to_smtp": sent_to_smtp,
                        "provider": outbox_provider,
                        "live_send_error": live_send_error})
    row.pop("_id", None)
    return row


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
