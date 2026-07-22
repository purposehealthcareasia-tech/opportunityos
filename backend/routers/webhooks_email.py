"""Email webhook receiver — Milestone C.

Handles inbound provider webhooks for email delivery/bounce/open events.
Hard-fails when the vendor signature-verification secret is not configured;
never accepts an unverified webhook (founder mandate: no bypass mode).

Route: `POST /api/webhook/email/{provider}`. CSRF middleware exempts the
`/api/webhook/*` prefix (see middleware/csrf.py).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from core.db import get_db
from core.time_utils import utc_now
from integrations import registry, health as integrations_health
from integrations.email.webhook_verifiers import (
    WebhookVerificationError, VerifiedWebhook,
)


log = logging.getLogger("oppos.webhooks.email")


router = APIRouter(prefix="/api/webhook/email", tags=["webhooks:email"])


@router.post("/{provider_slug}")
async def receive_email_webhook(provider_slug: str, request: Request):
    provider = registry.get(provider_slug)
    if not provider or getattr(provider, "category", None) is None \
            or provider.category.value != "email":
        raise HTTPException(status_code=404,
                             detail={"error": "unknown_email_provider"})
    if not hasattr(provider, "verify_webhook"):
        raise HTTPException(status_code=501,
                             detail={"error": "webhook_not_supported"})

    raw = await request.body()
    headers = {k: v for k, v in request.headers.items()}
    try:
        verified: VerifiedWebhook = provider.verify_webhook(  # type: ignore[attr-defined]
            raw_body=raw, headers=headers,
        )
    except WebhookVerificationError as e:
        # Semantic alignment with the internal-service-token convention:
        #   - webhook secret / public key not configured on server → HTTP 503
        #   - anything else (missing headers, bad signature, stale timestamp,
        #     malformed body) → HTTP 400
        # Never a 2xx, never a bypass.
        code = str(e)
        _SERVER_MISCONFIG = {
            "webhook_secret_not_configured",
            "webhook_public_key_not_configured",
        }
        # Runtime server misconfig (SendGrid PEM cannot be parsed because the
        # `cryptography` library is missing, or the operator pasted a bad
        # PEM) → 503. Vendor-side or client-side signature failure → 400.
        _SERVER_MISCONFIG_PREFIX = ("cryptography_missing", "bad_key_or_signature")
        status = 503 if (code in _SERVER_MISCONFIG
                          or code.startswith(_SERVER_MISCONFIG_PREFIX)) else 400
        # Record the rejection for the admin dashboard.
        await integrations_health.record_event(
            provider=provider_slug, kind="webhook_rejected",
            detail={"reason": code},
        )
        raise HTTPException(status_code=status,
                             detail={"error": "webhook_verification_failed",
                                     "reason": code})

    # Idempotent insert via unique index on (provider, external_event_id).
    # Guard the race between find_one and insert_one — vendors retry aggressively
    # and two concurrent duplicates would otherwise trigger a
    # `pymongo.errors.DuplicateKeyError` on the second insert, surfacing as
    # HTTP 500. That breaks the "never 500" invariant.
    from pymongo.errors import DuplicateKeyError
    db = get_db()
    existing = await db.webhook_events.find_one(
        {"provider": provider_slug, "external_event_id": verified.idempotency_key},
    )
    if existing:
        return {"status": "duplicate", "id": existing.get("id")}

    import uuid
    row_id = str(uuid.uuid4())
    try:
        await db.webhook_events.insert_one({
            "id": row_id,
            "provider": provider_slug,
            "external_event_id": verified.idempotency_key,
            "payload_json": verified.payload_json,
            "ts": utc_now(),
        })
    except DuplicateKeyError:
        # A concurrent request stored the same event id between our find_one
        # and this insert — safe to treat as a duplicate.
        row = await db.webhook_events.find_one(
            {"provider": provider_slug, "external_event_id": verified.idempotency_key},
        )
        return {"status": "duplicate", "id": (row or {}).get("id")}
    await integrations_health.record_event(
        provider=provider_slug, kind="webhook_received",
        detail={"external_event_id": verified.idempotency_key},
    )
    return {"status": "stored", "id": row_id}
