"""Payment webhook receiver — Milestone H.

Handles inbound payment webhooks for the four payment providers registered
in the unified integration layer:

    - stripe   (HMAC-SHA256, `Stripe-Signature` header)
    - razorpay (HMAC-SHA256, `X-Razorpay-Signature` header)
    - paystack (HMAC-SHA512, `x-paystack-signature` header)
    - paypal   (server-to-server signature verification round-trip)

Hard-fails on missing secret or invalid signature — never accepts a payload
without cryptographic proof (founder mandate: no bypass mode).

Route: `POST /api/webhook/payment/{provider_slug}`. CSRF middleware exempts
the `/api/webhook/*` prefix.

Deduplication:
    - stripe/razorpay/paystack: the raw payload's `id` / `event.id` field is
      pulled and stored as `external_event_id` in `webhook_events`.
    - paypal: `id` from PayPal's webhook_event body.
    The `webhook_events` collection carries a unique index on
    `(provider, external_event_id)` so replays return `status=duplicate`.
"""
from __future__ import annotations

import inspect
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request

from core.db import get_db
from core.time_utils import utc_now
from integrations import registry, health as integrations_health
from integrations.payments.signature_verifiers import PaymentSignatureError


log = logging.getLogger("oppos.webhooks.payment")


router = APIRouter(prefix="/api/webhook/payment", tags=["webhooks:payment"])


def _extract_external_event_id(provider_slug: str, raw: bytes) -> str:
    """Best-effort idempotency key extraction from the raw body.

    Vendor-specific notes:
      - Stripe / PayPal: top-level `id` is the event id — use as-is.
      - Paystack: `data.id` is the event id.
      - Razorpay: there is NO top-level event id. `payload.payment.entity.id`
        is the *payment* id and is STABLE across multiple events for one
        payment (authorized → captured → refunded). Using it alone would
        silently discard the second and third events as "duplicates" once
        Razorpay is live. We therefore compose the key from event name +
        payment id + created_at so different events for the same payment
        get distinct keys, while true vendor retries (identical body) still
        collide correctly.
      - Fallback: SHA-256 of the raw body (guarantees vendor-retry dedup).
    """
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        # If the body is not parseable JSON we fall back to a hash — the
        # webhook will still land, but replay protection uses the hash.
        import hashlib
        return f"hash:{hashlib.sha256(raw).hexdigest()[:32]}"
    if isinstance(payload, dict):
        # Razorpay: composite key of event + payment_id + created_at.
        if provider_slug == "razorpay":
            event = payload.get("event")
            created_at = payload.get("created_at")
            payment_id = None
            try:
                payment_id = (payload.get("payload") or {}).get("payment", {}).get("entity", {}).get("id")
            except Exception:
                pass
            if event and payment_id and created_at is not None:
                return f"rzp:{event}:{payment_id}:{created_at}"
            # Fall through to body-hash if Razorpay is missing any component.

        # Stripe/PayPal: `id` is the event id.
        for key in ("id", "event_id"):
            v = payload.get(key)
            if isinstance(v, str) and v:
                return v
        # Paystack canonical: {data:{id}}.
        try:
            v = (payload.get("data") or {}).get("id")
            if isinstance(v, (str, int)) and v:
                return str(v)
        except Exception:
            pass
    import hashlib
    return f"hash:{hashlib.sha256(raw).hexdigest()[:32]}"


@router.post("/{provider_slug}")
async def receive_payment_webhook(provider_slug: str, request: Request):
    provider = registry.get(provider_slug)
    if not provider or getattr(provider, "category", None) is None \
            or provider.category.value != "payments":
        raise HTTPException(status_code=404,
                             detail={"error": "unknown_payment_provider"})
    if not hasattr(provider, "verify_webhook"):
        raise HTTPException(status_code=501,
                             detail={"error": "webhook_not_supported"})

    raw = await request.body()
    headers = {k: v for k, v in request.headers.items()}

    try:
        vw = provider.verify_webhook(raw_body=raw, headers=headers)  # type: ignore[attr-defined]
        # PayPal's verify_webhook is async; the others are sync. Await if needed.
        if inspect.isawaitable(vw):
            await vw
    except PaymentSignatureError as e:
        code = str(e)
        # Semantic alignment with the internal-service-token convention:
        #   - webhook secret / webhook id / auth not configured on server → HTTP 503
        #     (operator has not finished configuring this provider)
        #   - anything else (missing/invalid headers, bad signature,
        #     stale timestamp, malformed body)                          → HTTP 400
        # Explicit allow-list avoids accidental 503-widening as future
        # error codes are added.
        _SERVER_MISCONFIG_EXACT = {
            "webhook_secret_not_configured",
            "webhook_id_not_configured",
        }
        _SERVER_MISCONFIG_PREFIX = (
            # PayPal server-to-server verification: OAuth token exchange
            # failed → auth_failed:...  |  network hiccup → upstream_error:...
            # PayPal verify endpoint returned non-2xx → verify_failed:HTTP N...
            # All are server-side / vendor-side problems, not client fault.
            "auth_failed",
            "upstream_error",
            "verify_failed",
        )
        server_misconfig = (
            code in _SERVER_MISCONFIG_EXACT
            or code.startswith(_SERVER_MISCONFIG_PREFIX)
        )
        status = 503 if server_misconfig else 400
        await integrations_health.record_event(
            provider=provider_slug, kind="webhook_rejected",
            detail={"reason": code[:120]},
        )
        raise HTTPException(status_code=status,
                             detail={"error": "webhook_verification_failed",
                                     "reason": code})

    external_event_id = _extract_external_event_id(provider_slug, raw)
    # Guard the race between find_one and insert_one — see webhooks_email.py
    # for the equivalent rationale. Vendors retry aggressively; two concurrent
    # duplicates must NEVER surface as HTTP 500.
    from pymongo.errors import DuplicateKeyError
    db = get_db()
    existing = await db.webhook_events.find_one({
        "provider": provider_slug, "external_event_id": external_event_id,
    })
    if existing:
        return {"status": "duplicate", "id": existing.get("id")}

    row_id = str(uuid.uuid4())
    try:
        payload_json = json.loads(raw.decode("utf-8"))
    except Exception:
        payload_json = None
    try:
        await db.webhook_events.insert_one({
            "id": row_id,
            "provider": provider_slug,
            "external_event_id": external_event_id,
            "payload_json": payload_json,
            "ts": utc_now(),
        })
    except DuplicateKeyError:
        row = await db.webhook_events.find_one({
            "provider": provider_slug, "external_event_id": external_event_id,
        })
        return {"status": "duplicate", "id": (row or {}).get("id")}
    await integrations_health.record_event(
        provider=provider_slug, kind="webhook_received",
        detail={"external_event_id": external_event_id[:120]},
    )
    return {"status": "stored", "id": row_id}
