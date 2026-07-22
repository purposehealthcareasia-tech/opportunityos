"""Code-review remediation regression tests (post-iteration-15).

Coverage:
  1. Razorpay dedup key composes event + payment_id + created_at — two
     distinct events for the same payment must yield distinct keys.
  2. Concurrent-duplicate webhook race — DuplicateKeyError from a second
     insert_one MUST return the same {status: duplicate} response, NEVER
     bubble up as HTTP 500. Enforced at the router level via a stubbed
     Motor collection.
  3. SendGrid `cryptography_missing` / `bad_key_or_signature` and PayPal
     `verify_failed:HTTP...` now map to HTTP 503, not 400.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

import pytest
from pymongo.errors import DuplicateKeyError


# ---------------------------------------------------------------------------
# 1. Razorpay dedup composition
# ---------------------------------------------------------------------------
class TestRazorpayDedupKey:
    def test_two_events_same_payment_distinct_keys(self):
        from routers.webhooks_payment import _extract_external_event_id
        pid = "pay_1234"
        raw_a = json.dumps({
            "event": "payment.authorized",
            "created_at": 1737400000,
            "payload": {"payment": {"entity": {"id": pid}}},
        }).encode()
        raw_b = json.dumps({
            "event": "payment.captured",
            "created_at": 1737400060,
            "payload": {"payment": {"entity": {"id": pid}}},
        }).encode()
        k_a = _extract_external_event_id("razorpay", raw_a)
        k_b = _extract_external_event_id("razorpay", raw_b)
        assert k_a != k_b, "Different events for the same payment must yield different keys"
        assert k_a.startswith("rzp:payment.authorized:pay_1234:")
        assert k_b.startswith("rzp:payment.captured:pay_1234:")

    def test_vendor_retry_of_same_event_collides(self):
        """A vendor retry sends the identical body twice — keys must match."""
        from routers.webhooks_payment import _extract_external_event_id
        raw = json.dumps({
            "event": "payment.captured",
            "created_at": 1737400060,
            "payload": {"payment": {"entity": {"id": "pay_1234"}}},
        }).encode()
        assert _extract_external_event_id("razorpay", raw) == \
               _extract_external_event_id("razorpay", raw)

    def test_missing_component_falls_back_to_hash(self):
        from routers.webhooks_payment import _extract_external_event_id
        # Missing created_at — must not silently reuse a stable key.
        raw = json.dumps({
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_1234"}}},
        }).encode()
        k = _extract_external_event_id("razorpay", raw)
        assert k.startswith("hash:")

    def test_stripe_and_paystack_extraction_still_correct(self):
        """Regression: the razorpay-branch must NOT affect other vendors."""
        from routers.webhooks_payment import _extract_external_event_id
        stripe_raw = json.dumps({"id": "evt_1", "type": "checkout.session.completed"}).encode()
        assert _extract_external_event_id("stripe", stripe_raw) == "evt_1"
        paystack_raw = json.dumps({"event": "charge.success", "data": {"id": 42}}).encode()
        assert _extract_external_event_id("paystack", paystack_raw) == "42"


# ---------------------------------------------------------------------------
# 2. Concurrent-duplicate insert must NOT return 500
# ---------------------------------------------------------------------------
class _CollStubDupe:
    """Motor-shaped stub that raises DuplicateKeyError on insert_one AFTER
    find_one returned None — simulating two concurrent inserts."""
    def __init__(self, prior_id: str | None):
        self._prior_id = prior_id
        self._find_call = 0
        self.stored_id = None

    async def find_one(self, filt, *a, **kw):
        self._find_call += 1
        # First find_one is called BEFORE the concurrent racer inserts — returns None.
        # Second find_one (post-DuplicateKeyError) returns the row the racer stored.
        if self._find_call == 1:
            return None
        return {"id": self._prior_id or "racer-inserted-id",
                "provider": "stripe",
                "external_event_id": "evt_race"}

    async def insert_one(self, *a, **kw):
        raise DuplicateKeyError("E11000 duplicate key error")

    async def create_index(self, *a, **kw):
        return None


class _DBStub:
    def __init__(self, coll):
        self.webhook_events = coll


@pytest.mark.asyncio
async def test_payment_webhook_race_returns_duplicate_not_500(monkeypatch):
    """Simulate: find_one → None (race), insert_one → DuplicateKeyError.
    Router must recover and return status=duplicate, NOT let the exception
    bubble up as HTTP 500."""
    from routers import webhooks_payment as pw

    coll = _CollStubDupe(prior_id="racer-abc")
    stub_db = _DBStub(coll)
    monkeypatch.setattr(pw, "get_db", lambda: stub_db)

    # Also stub the health-event recorder so we don't touch the real DB.
    async def _noop(**kw): return None
    monkeypatch.setattr(pw.integrations_health, "record_event", _noop)

    # Fake provider that verifies happily.
    class _FakeProvider:
        class category:
            value = "payments"
        def verify_webhook(self, *, raw_body, headers):
            return None
    monkeypatch.setattr(pw.registry, "get", lambda slug: _FakeProvider())

    from fastapi import Request
    from starlette.datastructures import Headers

    class _FakeReq:
        headers = Headers({"content-type": "application/json"})
        async def body(self):
            return b'{"id":"evt_race"}'

    result = await pw.receive_payment_webhook("stripe", _FakeReq())  # type: ignore[arg-type]
    assert result["status"] == "duplicate"
    assert result["id"] == "racer-abc"


@pytest.mark.asyncio
async def test_email_webhook_race_returns_duplicate_not_500(monkeypatch):
    """Same rationale as above for the email route."""
    from routers import webhooks_email as ew

    coll = _CollStubDupe(prior_id="racer-eml")
    stub_db = _DBStub(coll)
    monkeypatch.setattr(ew, "get_db", lambda: stub_db)

    async def _noop(**kw): return None
    monkeypatch.setattr(ew.integrations_health, "record_event", _noop)

    class _V:
        idempotency_key = "svix_evt_race"
        payload_json = {"type": "email.delivered"}
        provider = "resend"

    class _FakeProvider:
        class category:
            value = "email"
        def verify_webhook(self, *, raw_body, headers):
            return _V()
    monkeypatch.setattr(ew.registry, "get", lambda slug: _FakeProvider())

    from starlette.datastructures import Headers

    class _FakeReq:
        headers = Headers({"content-type": "application/json"})
        async def body(self):
            return b'{"type":"email.delivered"}'

    result = await ew.receive_email_webhook("resend", _FakeReq())  # type: ignore[arg-type]
    assert result["status"] == "duplicate"
    assert result["id"] == "racer-eml"


# ---------------------------------------------------------------------------
# 3. Status-code mapping refinements
# ---------------------------------------------------------------------------
class TestStatusMappingRefined:
    def test_sendgrid_cryptography_missing_now_503(self):
        """Missing `cryptography` lib is a server-side / packaging problem.
        Route must return 503, not 400 (client is not at fault)."""
        from fastapi import HTTPException
        from routers import webhooks_email as ew

        # Fake provider whose verify_webhook raises with 'cryptography_missing:...'.
        class _FakeProvider:
            class category:
                value = "email"
            def verify_webhook(self, *, raw_body, headers):
                from integrations.email.webhook_verifiers import WebhookVerificationError
                raise WebhookVerificationError("cryptography_missing: no such module 'cryptography'")

        import pytest as _pt
        from starlette.datastructures import Headers

        class _FakeReq:
            headers = Headers({})
            async def body(self):
                return b"{}"

        async def _run(monkeypatch):
            monkeypatch.setattr(ew.registry, "get", lambda slug: _FakeProvider())
            async def _noop(**kw): return None
            monkeypatch.setattr(ew.integrations_health, "record_event", _noop)
            try:
                await ew.receive_email_webhook("sendgrid", _FakeReq())  # type: ignore[arg-type]
                _pt.fail("expected HTTPException")
            except HTTPException as e:
                return e

        # Emulate a monkeypatch context.
        mp = _pt.MonkeyPatch()
        try:
            e = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_run(mp))
        finally:
            mp.undo()
        assert e.status_code == 503, f"expected 503, got {e.status_code}"

    def test_paypal_verify_failed_upstream_now_503(self):
        """PayPal verify endpoint returned non-2xx (`verify_failed:HTTP 5xx`).
        That is an upstream/server-side problem; route must return 503."""
        from fastapi import HTTPException
        from routers import webhooks_payment as pw
        from integrations.payments.signature_verifiers import PaymentSignatureError
        import pytest as _pt
        from starlette.datastructures import Headers

        class _FakeProvider:
            class category:
                value = "payments"
            async def verify_webhook(self, *, raw_body, headers):
                raise PaymentSignatureError("verify_failed:HTTP 503")

        class _FakeReq:
            headers = Headers({})
            async def body(self):
                return b"{}"

        async def _run(monkeypatch):
            monkeypatch.setattr(pw.registry, "get", lambda slug: _FakeProvider())
            async def _noop(**kw): return None
            monkeypatch.setattr(pw.integrations_health, "record_event", _noop)
            try:
                await pw.receive_payment_webhook("paypal", _FakeReq())  # type: ignore[arg-type]
                _pt.fail("expected HTTPException")
            except HTTPException as e:
                return e

        mp = _pt.MonkeyPatch()
        try:
            e = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_run(mp))
        finally:
            mp.undo()
        assert e.status_code == 503, f"expected 503, got {e.status_code}"
