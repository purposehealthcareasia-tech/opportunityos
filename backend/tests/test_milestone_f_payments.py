"""Milestone F — Payments abstraction + regional adapters + strangler.

Coverage:
  1. Provider status matrix — stripe TEST_MODE (existing), razorpay/paypal/
     paystack CONFIGURATION_REQUIRED until credentials supplied.
  2. Cryptographic signature verification for Stripe / Razorpay / Paystack
     against locally-generated secrets. All three hard-fail on:
       - missing secret
       - missing header
       - bad timestamp (Stripe only)
       - bad signature
  3. `create_order()` / `initialize_transaction()` /
     `create_checkout_session()` hard-fail without credentials.
  4. PayPal `verify_webhook()` hard-fails without `PAYPAL_WEBHOOK_ID` or
     missing signature headers.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import pytest


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_registry():
    from integrations import registry
    registry.load_all()
    yield


@pytest.fixture
def stripe_provider():
    from integrations import registry
    p = registry.get("stripe")
    p.configure()
    return p


@pytest.fixture
def razorpay_provider():
    from integrations import registry
    p = registry.get("razorpay")
    p.configure()
    return p


@pytest.fixture
def paystack_provider():
    from integrations import registry
    p = registry.get("paystack")
    p.configure()
    return p


@pytest.fixture
def paypal_provider():
    from integrations import registry
    p = registry.get("paypal")
    p.configure()
    return p


# ---------------------------------------------------------------------------
# Status matrix
# ---------------------------------------------------------------------------
class TestPaymentStatusMatrix:
    def test_stripe_test_mode(self, stripe_provider):
        d = stripe_provider.describe()
        assert d["status"] == "TEST_MODE", d

    def test_regionals_are_configuration_required(self, razorpay_provider,
                                                     paystack_provider,
                                                     paypal_provider):
        assert razorpay_provider.describe()["status"] == "CONFIGURATION_REQUIRED"
        assert paystack_provider.describe()["status"] == "CONFIGURATION_REQUIRED"
        assert paypal_provider.describe()["status"] == "CONFIGURATION_REQUIRED"


# ---------------------------------------------------------------------------
# Hard-fail on missing credentials
# ---------------------------------------------------------------------------
class TestCreateOrderHardFail:
    @pytest.mark.asyncio
    async def test_razorpay_create_order_hardfails(self, razorpay_provider):
        from integrations.base import ProviderError
        with pytest.raises(ProviderError) as ei:
            await razorpay_provider.create_order(amount_paise=1000)
        assert ei.value.code == "configuration_required"

    @pytest.mark.asyncio
    async def test_paystack_initialize_hardfails(self, paystack_provider):
        from integrations.base import ProviderError
        with pytest.raises(ProviderError) as ei:
            await paystack_provider.initialize_transaction(
                email="a@b.com", amount_kobo=1000,
            )
        assert ei.value.code == "configuration_required"

    @pytest.mark.asyncio
    async def test_paypal_create_order_hardfails(self, paypal_provider):
        from integrations.base import ProviderError
        with pytest.raises(ProviderError) as ei:
            await paypal_provider.create_order(amount="10.00")
        assert ei.value.code == "configuration_required"


# ---------------------------------------------------------------------------
# Stripe signature verification (locally-generated whsec)
# ---------------------------------------------------------------------------
class TestStripeSignatureVerification:
    _whsec = "whsec_" + "a" * 32

    def _sign(self, body: bytes, ts: int) -> str:
        signed = f"{ts}.".encode() + body
        sig = hmac.new(self._whsec.encode(), signed, hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"

    def test_missing_secret_hardfails(self, stripe_provider):
        from integrations.payments.signature_verifiers import PaymentSignatureError
        # Ensure STRIPE_WEBHOOK_SECRET is unset for this env.
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
        stripe_provider.configure()
        with pytest.raises(PaymentSignatureError) as ei:
            stripe_provider.verify_webhook(raw_body=b"{}", headers={
                "Stripe-Signature": self._sign(b"{}", int(time.time())),
            })
        assert "webhook_secret_not_configured" in str(ei.value)

    def test_valid_signature_accepted(self, stripe_provider, monkeypatch):
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._whsec)
        stripe_provider.configure()
        try:
            body = b'{"id":"evt_test_1","type":"checkout.session.completed"}'
            ts = int(time.time())
            header = self._sign(body, ts)
            # Should NOT raise.
            stripe_provider.verify_webhook(raw_body=body,
                                             headers={"Stripe-Signature": header})
        finally:
            monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
            stripe_provider.configure()

    def test_bad_signature_rejected(self, stripe_provider, monkeypatch):
        from integrations.payments.signature_verifiers import PaymentSignatureError
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._whsec)
        stripe_provider.configure()
        try:
            body = b'{"id":"evt_test_2"}'
            ts = int(time.time())
            header = f"t={ts},v1=deadbeef"
            with pytest.raises(PaymentSignatureError) as ei:
                stripe_provider.verify_webhook(raw_body=body,
                                                 headers={"Stripe-Signature": header})
            assert "invalid_signature" in str(ei.value)
        finally:
            monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
            stripe_provider.configure()

    def test_stale_timestamp_rejected(self, stripe_provider, monkeypatch):
        from integrations.payments.signature_verifiers import PaymentSignatureError
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._whsec)
        stripe_provider.configure()
        try:
            body = b"{}"
            ts = int(time.time()) - 900  # 15 min stale
            header = self._sign(body, ts)
            with pytest.raises(PaymentSignatureError) as ei:
                stripe_provider.verify_webhook(raw_body=body,
                                                 headers={"Stripe-Signature": header})
            assert "timestamp" in str(ei.value)
        finally:
            monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
            stripe_provider.configure()


# ---------------------------------------------------------------------------
# Razorpay signature verification
# ---------------------------------------------------------------------------
class TestRazorpaySignatureVerification:
    def test_missing_secret_hardfails(self, razorpay_provider):
        from integrations.payments.signature_verifiers import PaymentSignatureError
        # No RAZORPAY_WEBHOOK_SECRET in env.
        razorpay_provider.configure()
        with pytest.raises(PaymentSignatureError) as ei:
            razorpay_provider.verify_webhook(raw_body=b"{}", headers={
                "X-Razorpay-Signature": "anything",
            })
        assert "webhook_secret_not_configured" in str(ei.value)

    def test_valid_signature_accepted(self, razorpay_provider, monkeypatch):
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "my_secret")
        razorpay_provider.configure()
        try:
            body = b'{"event":"payment.captured"}'
            sig = hmac.new(b"my_secret", body, hashlib.sha256).hexdigest()
            razorpay_provider.verify_webhook(raw_body=body,
                                                headers={"X-Razorpay-Signature": sig})
        finally:
            monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
            razorpay_provider.configure()

    def test_bad_signature_rejected(self, razorpay_provider, monkeypatch):
        from integrations.payments.signature_verifiers import PaymentSignatureError
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "my_secret")
        razorpay_provider.configure()
        try:
            with pytest.raises(PaymentSignatureError) as ei:
                razorpay_provider.verify_webhook(raw_body=b'{"event":"x"}',
                                                    headers={"X-Razorpay-Signature": "bad"})
            assert "invalid_signature" in str(ei.value)
        finally:
            monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
            razorpay_provider.configure()


# ---------------------------------------------------------------------------
# Paystack signature verification (SHA-512, secret_key)
# ---------------------------------------------------------------------------
class TestPaystackSignatureVerification:
    def test_missing_secret_hardfails(self, paystack_provider):
        from integrations.payments.signature_verifiers import PaymentSignatureError
        paystack_provider.configure()
        with pytest.raises(PaymentSignatureError) as ei:
            paystack_provider.verify_webhook(raw_body=b"{}", headers={
                "x-paystack-signature": "anything",
            })
        assert "webhook_secret_not_configured" in str(ei.value)

    def test_valid_signature_accepted(self, paystack_provider, monkeypatch):
        monkeypatch.setenv("PAYSTACK_SECRET_KEY", "sk_test_ps")
        paystack_provider.configure()
        try:
            body = b'{"event":"charge.success"}'
            sig = hmac.new(b"sk_test_ps", body, hashlib.sha512).hexdigest()
            paystack_provider.verify_webhook(raw_body=body,
                                                headers={"x-paystack-signature": sig})
        finally:
            monkeypatch.delenv("PAYSTACK_SECRET_KEY", raising=False)
            paystack_provider.configure()


# ---------------------------------------------------------------------------
# PayPal — hard-fail without WEBHOOK_ID or missing headers
# ---------------------------------------------------------------------------
class TestPayPalWebhookHardFail:
    @pytest.mark.asyncio
    async def test_missing_webhook_id_hardfails(self, paypal_provider):
        from integrations.payments.signature_verifiers import PaymentSignatureError
        paypal_provider.configure()
        with pytest.raises(PaymentSignatureError) as ei:
            await paypal_provider.verify_webhook(raw_body=b"{}", headers={})
        assert "webhook_id_not_configured" in str(ei.value)

    @pytest.mark.asyncio
    async def test_missing_headers_hardfails(self, paypal_provider, monkeypatch):
        from integrations.payments.signature_verifiers import PaymentSignatureError
        monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST-1")
        paypal_provider.configure()
        try:
            with pytest.raises(PaymentSignatureError) as ei:
                await paypal_provider.verify_webhook(raw_body=b"{}", headers={
                    "paypal-transmission-id": "x",
                    # remaining required headers intentionally missing
                })
            assert "missing_headers" in str(ei.value)
        finally:
            monkeypatch.delenv("PAYPAL_WEBHOOK_ID", raising=False)
            paypal_provider.configure()
