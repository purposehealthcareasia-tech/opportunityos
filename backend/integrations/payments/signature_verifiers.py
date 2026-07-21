"""Shared payment provider primitives — signature helpers + errors.

Verification helpers are pure functions (no I/O) so they can be exercised
against locally-generated secrets without vendor keys. Every helper
hard-fails on missing secret / bad signature — no bypass mode ever.

Coverage per vendor:
    - Stripe:   HMAC-SHA256 over `{ts}.{raw_body}` in `Stripe-Signature`.
    - Razorpay: HMAC-SHA256 over `raw_body` in `X-Razorpay-Signature`.
    - Paystack: HMAC-SHA512 over `raw_body` in `x-paystack-signature`.
    - PayPal:   PayPal requires an outbound `/v1/notifications/verify-webhook-
                signature` call. That is a network step, not a pure helper,
                so a `PayPalSignatureVerifier` service does the work instead
                (implemented in the paypal_provider adapter itself). This
                module only carries the shared error type.
"""
from __future__ import annotations

import hashlib
import hmac
import time


class PaymentSignatureError(Exception):
    """Raised when a payment-webhook signature check fails."""


def verify_stripe_signature(*, raw_body: bytes, header: str,
                              webhook_secret: str,
                              tolerance_seconds: int = 300) -> None:
    """Verify Stripe's `Stripe-Signature` header.

    Header format: `t=<unix_ts>,v1=<hex_hmac>[,v0=<hex_hmac>]`.
    Signed payload: `{t}.{raw_body}` — HMAC-SHA256 with the whsec.
    """
    if not webhook_secret:
        raise PaymentSignatureError("webhook_secret_not_configured")
    if not header:
        raise PaymentSignatureError("missing_signature_header")
    parts = {}
    for kv in header.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            parts.setdefault(k.strip(), []).append(v.strip())
    ts_list = parts.get("t") or []
    sig_list = parts.get("v1") or []
    if not ts_list or not sig_list:
        raise PaymentSignatureError("malformed_signature_header")
    try:
        ts_int = int(ts_list[0])
    except ValueError as e:
        raise PaymentSignatureError("bad_timestamp") from e
    if abs(int(time.time()) - ts_int) > tolerance_seconds:
        raise PaymentSignatureError("timestamp_out_of_tolerance")
    signed = f"{ts_list[0]}.".encode("utf-8") + raw_body
    expected = hmac.new(webhook_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sig_list):
        raise PaymentSignatureError("invalid_signature")


def verify_razorpay_signature(*, raw_body: bytes, header: str,
                                webhook_secret: str) -> None:
    """Verify Razorpay's `X-Razorpay-Signature` header (HMAC-SHA256 hex)."""
    if not webhook_secret:
        raise PaymentSignatureError("webhook_secret_not_configured")
    if not header:
        raise PaymentSignatureError("missing_signature_header")
    expected = hmac.new(webhook_secret.encode("utf-8"), raw_body,
                          hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header):
        raise PaymentSignatureError("invalid_signature")


def verify_paystack_signature(*, raw_body: bytes, header: str,
                                webhook_secret: str) -> None:
    """Verify Paystack's `x-paystack-signature` header (HMAC-SHA512 hex)."""
    if not webhook_secret:
        raise PaymentSignatureError("webhook_secret_not_configured")
    if not header:
        raise PaymentSignatureError("missing_signature_header")
    expected = hmac.new(webhook_secret.encode("utf-8"), raw_body,
                          hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, header):
        raise PaymentSignatureError("invalid_signature")
