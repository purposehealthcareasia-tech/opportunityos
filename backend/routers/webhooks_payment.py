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
    """Best-effort idempotency key extraction from the raw body."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        # If the body is not parseable JSON we fall back to a hash — the
        # webhook will still land, but replay protection uses the hash.
        import hashlib
        return f"hash:{hashlib.sha256(raw).hexdigest()[:32]}"
    if isinstance(payload, dict):
        # Stripe/PayPal: {id:"evt_..."}. Razorpay: {payload:{payment:{entity:{id}}}}.
        # Paystack: {data:{id}}.
        for key in ("id", "event_id"):
            v = payload.get(key)
            if isinstance(v, str) and v:
                return v
        # Razorpay canonical: payment/order.id under payload.
        try:
            v = (payload.get("payload") or {}).get("payment", {}).get("entity", {}).get("id")
            if isinstance(v, str) and v:
                return v
        except Exception:
            pass
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
        # 500 = "the operator has not finished configuring this provider".
        # 400 = "the vendor sent a payload with an invalid signature".
        status = 500 if code.endswith("not_configured") else 400
        await integrations_health.record_event(
            provider=provider_slug, kind="webhook_rejected",
            detail={"reason": code[:120]},
        )
        raise HTTPException(status_code=status,
                             detail={"error": "webhook_verification_failed",
                                     "reason": code})

    external_event_id = _extract_external_event_id(provider_slug, raw)
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
    await db.webhook_events.insert_one({
        "id": row_id,
        "provider": provider_slug,
        "external_event_id": external_event_id,
        "payload_json": payload_json,
        "ts": utc_now(),
    })
    await integrations_health.record_event(
        provider=provider_slug, kind="webhook_received",
        detail={"external_event_id": external_event_id[:120]},
    )
    return {"status": "stored", "id": row_id}
