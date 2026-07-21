"""Shared email provider primitives — signature helpers + normalized errors.

Both Resend and SendGrid adapters build on top of this file so the webhook
route in `routers/webhooks_email.py` can dispatch by slug without knowing
vendor internals. Signature verification NEVER falls back to a bypass mode —
missing secrets produce a hard failure per founder mandate.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass


class WebhookVerificationError(Exception):
    """Raised when a webhook fails signature/timestamp verification.

    The route catches this and returns HTTP 400 without recording the payload.
    """


@dataclass
class VerifiedWebhook:
    """Result of a successful vendor webhook verification."""
    idempotency_key: str  # sg_event_id for SendGrid, svix-id for Resend, etc.
    provider: str
    payload_json: dict | list | None
    payload_text: str


def verify_svix_signature(*, raw_body: bytes, headers: dict[str, str],
                            webhook_secret: str,
                            tolerance_seconds: int = 300) -> VerifiedWebhook:
    """Verify a Svix-style webhook (used by Resend).

    Canonical string: `{svix-id}.{svix-timestamp}.{raw_body}` signed with
    HMAC-SHA256 using the base64-decoded portion of `whsec_<b64>`. The header
    `svix-signature` is a space-separated list of `v1,<b64_signature>` pairs.
    """
    if not webhook_secret:
        raise WebhookVerificationError("webhook_secret_not_configured")
    svix_id = headers.get("svix-id") or headers.get("Svix-Id")
    svix_ts = headers.get("svix-timestamp") or headers.get("Svix-Timestamp")
    svix_sig = headers.get("svix-signature") or headers.get("Svix-Signature")
    if not all([svix_id, svix_ts, svix_sig]):
        raise WebhookVerificationError("missing_svix_headers")

    # Replay protection.
    try:
        ts_int = int(svix_ts)
    except ValueError as e:
        raise WebhookVerificationError("bad_timestamp") from e
    if abs(int(time.time()) - ts_int) > tolerance_seconds:
        raise WebhookVerificationError("timestamp_out_of_tolerance")

    if not webhook_secret.startswith("whsec_"):
        raise WebhookVerificationError("bad_secret_format")
    key_bytes = base64.b64decode(webhook_secret.split("_", 1)[1])

    signed_content = f"{svix_id}.{svix_ts}.".encode("utf-8") + raw_body
    computed = base64.b64encode(
        hmac.new(key_bytes, signed_content, hashlib.sha256).digest()
    ).decode("utf-8")

    valid = False
    for sig_entry in svix_sig.split(" "):
        if "," not in sig_entry:
            continue
        _, sig = sig_entry.split(",", 1)
        if hmac.compare_digest(sig, computed):
            valid = True
            break
    if not valid:
        raise WebhookVerificationError("invalid_signature")

    payload_text = raw_body.decode("utf-8", errors="replace")
    try:
        payload_json = json.loads(payload_text) if payload_text else None
    except json.JSONDecodeError:
        payload_json = None
    return VerifiedWebhook(idempotency_key=svix_id, provider="resend",
                            payload_json=payload_json, payload_text=payload_text)


def verify_sendgrid_signature(*, raw_body: bytes, headers: dict[str, str],
                                 public_key_pem: str,
                                 tolerance_seconds: int = 300) -> VerifiedWebhook:
    """Verify a Twilio SendGrid ECDSA-signed event webhook.

    Canonical string: `timestamp + raw_body`; hash SHA-256; verify ECDSA(P-256).
    The public key is the PEM shown in the SendGrid dashboard once signed
    webhooks are enabled.
    """
    if not public_key_pem:
        raise WebhookVerificationError("webhook_public_key_not_configured")
    sig_b64 = headers.get("X-Twilio-Email-Event-Webhook-Signature") or headers.get("x-twilio-email-event-webhook-signature")
    ts = headers.get("X-Twilio-Email-Event-Webhook-Timestamp") or headers.get("x-twilio-email-event-webhook-timestamp")
    if not sig_b64 or not ts:
        raise WebhookVerificationError("missing_sendgrid_headers")

    try:
        ts_int = int(ts)
    except ValueError as e:
        raise WebhookVerificationError("bad_timestamp") from e
    if abs(int(time.time()) - ts_int) > tolerance_seconds:
        raise WebhookVerificationError("timestamp_out_of_tolerance")

    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils as ec_utils
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.exceptions import InvalidSignature
    except ImportError as e:  # pragma: no cover
        raise WebhookVerificationError(f"cryptography_missing: {e}") from e

    try:
        signature = base64.b64decode(sig_b64)
        pub = load_pem_public_key(public_key_pem.encode("utf-8"))
    except Exception as e:
        raise WebhookVerificationError(f"bad_key_or_signature: {e}") from e

    data = ts.encode("utf-8") + raw_body
    try:
        pub.verify(signature, data, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as e:
        raise WebhookVerificationError("invalid_signature") from e
    except Exception as e:
        raise WebhookVerificationError(f"verify_error: {e}") from e

    payload_text = raw_body.decode("utf-8", errors="replace")
    try:
        payload_json = json.loads(payload_text) if payload_text else None
    except json.JSONDecodeError:
        payload_json = None

    # Extract sg_event_id — playbook-recommended idempotency key.
    idem = None
    if isinstance(payload_json, list) and payload_json:
        idem = (payload_json[0] or {}).get("sg_event_id")
    elif isinstance(payload_json, dict):
        idem = payload_json.get("sg_event_id")
    if not idem:
        raise WebhookVerificationError("missing_sg_event_id")

    return VerifiedWebhook(idempotency_key=idem, provider="sendgrid",
                            payload_json=payload_json, payload_text=payload_text)
