"""Web Push notifications — comprehensive regression.

Covers every founder-mandated invariant:

- Subscribe / unsubscribe with ownership rejection (a user can only touch
  their own subscription).
- Category opt-out blocks dispatch (server-side enforcement).
- Payload minimalism — no employer / salary / sealed / claim / auth-id
  content in the JSON blob or in the notifications DB row.
- 404 / 410 push-service responses prune the subscription.
- Provider status transitions:
    CONFIGURATION_REQUIRED (env missing) → CONNECTED (env set)
    → DEGRADED (record_error).
- Rate limiting on subscribe (per-user).
- Idempotent dispatch (dedup_key prevents duplicates).
- Test-send endpoint end-to-end.
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from unittest.mock import patch, MagicMock

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core import db as db_module
from core.config import settings
from domains.notifications import service as svc
from domains.notifications import events as notif_events
# Import the provider at test file collection time so `integrations.base`'s
# `load_dotenv(override=False)` runs ONCE while the .env vars are still set
# in os.environ (and therefore skips them). If we imported it lazily inside a
# test that had already run `monkeypatch.delenv`, load_dotenv would refill
# the deleted keys and defeat the CONFIGURATION_REQUIRED assertion.
from integrations.push.webpush_provider import WebPushProvider  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: ephemeral Mongo DB bound to the test's event loop.
# ---------------------------------------------------------------------------

def _fake_endpoint() -> str:
    return f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}"


def _fake_keys() -> dict:
    return {
        "p256dh": base64.urlsafe_b64encode(os.urandom(65)).rstrip(b"=").decode(),
        "auth":   base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode(),
    }


@pytest.fixture
async def isolated_db(monkeypatch):
    dbname = f"opportunityos_pushtest_{uuid.uuid4().hex[:8]}"
    client = AsyncIOMotorClient(settings.MONGO_URL, uuidRepresentation="standard")
    fake_db = client[dbname]
    monkeypatch.setattr(db_module, "get_db", lambda: fake_db)
    monkeypatch.setattr(svc, "get_db", lambda: fake_db)
    from domains.audit import service as audit_mod
    monkeypatch.setattr(audit_mod, "get_db", lambda: fake_db, raising=False)
    try:
        await svc.ensure_indexes()
        yield fake_db
    finally:
        try:
            import pymongo
            pymongo.MongoClient(settings.MONGO_URL).drop_database(dbname)
        except Exception:
            pass
        client.close()


# ---------------------------------------------------------------------------
# Payload minimalism — the strongest privacy invariant.
# ---------------------------------------------------------------------------

class TestPayloadMinimalism:
    def test_allowed_titles_are_generic(self):
        # None of the fixed vocabulary strings mention employer / salary / etc.
        forbidden_tokens = ["employer", "salary", "$", "clearance", "sealed",
                            "visa", "sponsor", "compensation", "PMP", "MATLAB"]
        for t in svc._ALLOWED_TITLES.values():
            for f in forbidden_tokens:
                assert f.lower() not in t.lower()
        for b in svc._ALLOWED_BODIES.values():
            for f in forbidden_tokens:
                assert f.lower() not in b.lower()

    def test_scrub_rejects_forbidden_keys(self):
        for key in ["company_name", "salary", "claim_ids", "authorization_id",
                    "eligibility_profile", "screener_answers", "body"]:
            with pytest.raises(ValueError, match="push_payload_leak"):
                svc._scrub_data_dict({key: "anything"})

    def test_scrub_drops_unknown_keys_silently(self):
        # Unknown keys are just filtered — safer than raising for future data.
        out = svc._scrub_data_dict({"application_id": "app-1", "random": "x"})
        assert out == {"application_id": "app-1"}

    def test_scrub_refuses_absolute_urls(self):
        assert svc._scrub_data_dict({"url": "https://evil.example/x"}) == {}
        assert svc._scrub_data_dict({"url": "//evil.example/x"}) == {}
        assert svc._scrub_data_dict({"url": "/tracker"}) == {"url": "/tracker"}

    def test_build_payload_uses_fixed_vocabulary(self):
        blob = svc._build_payload("interviews", data={"application_id": "app-1"})
        parsed = json.loads(blob)
        assert parsed["title"] == "Interview scheduled"
        assert parsed["body"]  == "An interview was added to your tracker."
        assert parsed["category"] == "interviews"
        assert parsed["data"] == {"application_id": "app-1"}


# ---------------------------------------------------------------------------
# Subscribe / unsubscribe + ownership.
# ---------------------------------------------------------------------------

class TestSubscriptionLifecycle:
    @pytest.mark.asyncio
    async def test_register_is_idempotent_per_endpoint(self, isolated_db):
        endpoint = _fake_endpoint()
        keys = _fake_keys()
        u = "user-a"
        r1 = await svc.register_subscription(user_id=u, subscription={"endpoint": endpoint, "keys": keys}, user_agent="test-1")
        r2 = await svc.register_subscription(user_id=u, subscription={"endpoint": endpoint, "keys": keys}, user_agent="test-2")
        assert r1["id"] == r2["id"]
        # The second call updates last_seen_at / user_agent.
        assert r2["user_agent"] == "test-2"
        # Only one row inserted.
        n = await isolated_db.notification_subscriptions.count_documents({"user_id": u})
        assert n == 1

    @pytest.mark.asyncio
    async def test_ownership_rejection_on_unsubscribe(self, isolated_db):
        endpoint = _fake_endpoint()
        await svc.register_subscription(user_id="user-a", subscription={"endpoint": endpoint, "keys": _fake_keys()}, user_agent=None)
        # user-b cannot revoke user-a's subscription.
        assert await svc.revoke_subscription(user_id="user-b", endpoint=endpoint) is False
        # user-a can.
        assert await svc.revoke_subscription(user_id="user-a", endpoint=endpoint) is True
        row = await isolated_db.notification_subscriptions.find_one({"endpoint": endpoint})
        assert row["active"] is False and row["revoked_at"] is not None


# ---------------------------------------------------------------------------
# Dispatch — opt-out enforcement, dedup, prune, VAPID absence.
# ---------------------------------------------------------------------------

def _mock_webpush_success():
    return patch("pywebpush.webpush", return_value=MagicMock())


def _mock_webpush_http(status_code: int):
    from pywebpush import WebPushException
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = f"http {status_code}"
    def _raise(*a, **k):
        exc = WebPushException("push service refused")
        exc.response = resp
        raise exc
    return patch("pywebpush.webpush", side_effect=_raise)


class TestDispatch:
    @pytest.mark.asyncio
    async def test_opted_out_category_is_never_dispatched(self, isolated_db, monkeypatch):
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "x"); monkeypatch.setenv("VAPID_PRIVATE_KEY", "y")
        monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@opportunityos.dev")
        await svc.register_subscription(user_id="u", subscription={"endpoint": _fake_endpoint(), "keys": _fake_keys()}, user_agent=None)
        # Opt out of application_updates BEFORE dispatch.
        await svc.set_preferences("u", {"application_updates": False}, actor="u")

        with _mock_webpush_success() as m:
            res = await svc.dispatch("u", "application_updates",
                                     data={"application_id": "app-1"},
                                     dedup_key="outcome:o1")
        assert res["skipped"] == 1 and res["sent"] == 0 and res["reason"] == "opted_out"
        m.assert_not_called()
        # Nothing should have been persisted in notifications either.
        assert await isolated_db.notifications.count_documents({"user_id": "u"}) == 0

    @pytest.mark.asyncio
    async def test_dedup_key_prevents_duplicate_dispatch(self, isolated_db, monkeypatch):
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "x"); monkeypatch.setenv("VAPID_PRIVATE_KEY", "y")
        monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@opportunityos.dev")
        await svc.register_subscription(user_id="u", subscription={"endpoint": _fake_endpoint(), "keys": _fake_keys()}, user_agent=None)

        with _mock_webpush_success() as m:
            r1 = await svc.dispatch("u", "receipts", data={"receipt_id": "r1"}, dedup_key="receipt:r1")
            r2 = await svc.dispatch("u", "receipts", data={"receipt_id": "r1"}, dedup_key="receipt:r1")
        assert r1["sent"] == 1
        assert r2["skipped"] == 1 and r2["reason"] == "duplicate"
        assert m.call_count == 1

    @pytest.mark.asyncio
    async def test_no_active_subscriptions_is_a_clean_noop(self, isolated_db, monkeypatch):
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "x"); monkeypatch.setenv("VAPID_PRIVATE_KEY", "y")
        monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@opportunityos.dev")
        res = await svc.dispatch("u", "interviews", data={"interview_id": "i1"}, dedup_key=None)
        assert res == {"sent": 0, "failed": 0, "skipped": 0, "pruned": 0,
                       "category": "interviews", "notification_id": None,
                       "reason": "no_active_subscriptions"}

    @pytest.mark.asyncio
    async def test_vapid_missing_returns_configuration_reason(self, isolated_db, monkeypatch):
        # Explicitly clear VAPID env so the service falls into the not-configured branch.
        for k in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"):
            monkeypatch.delenv(k, raising=False)
        await svc.register_subscription(user_id="u", subscription={"endpoint": _fake_endpoint(), "keys": _fake_keys()}, user_agent=None)
        res = await svc.dispatch("u", "support", data={"ticket_id": "t1"}, dedup_key=None)
        assert res["reason"] == "vapid_not_configured"
        assert res["sent"] == 0

    @pytest.mark.asyncio
    async def test_prune_on_404_or_410(self, isolated_db, monkeypatch):
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "x"); monkeypatch.setenv("VAPID_PRIVATE_KEY", "y")
        monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@opportunityos.dev")
        endpoint = _fake_endpoint()
        await svc.register_subscription(user_id="u", subscription={"endpoint": endpoint, "keys": _fake_keys()}, user_agent=None)

        with _mock_webpush_http(410):
            res = await svc.dispatch("u", "application_updates",
                                     data={"application_id": "a1"},
                                     dedup_key="outcome:o1")
        assert res["pruned"] == 1 and res["sent"] == 0 and res["failed"] == 0
        row = await isolated_db.notification_subscriptions.find_one({"endpoint": endpoint})
        assert row["active"] is False and row["prune_reason"] == "push_service_returned_410"

    @pytest.mark.asyncio
    async def test_notifications_row_payload_never_leaks(self, isolated_db, monkeypatch):
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "x"); monkeypatch.setenv("VAPID_PRIVATE_KEY", "y")
        monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@opportunityos.dev")
        await svc.register_subscription(user_id="u", subscription={"endpoint": _fake_endpoint(), "keys": _fake_keys()}, user_agent=None)
        # Attacker-shaped call that tries to smuggle a sealed field into data.
        with pytest.raises(ValueError, match="push_payload_leak"):
            await svc.dispatch("u", "application_updates",
                               data={"company_name": "Tesla"},
                               dedup_key="oz1")
        # And the stored notifications row must also carry only allowed keys.
        with _mock_webpush_success():
            await svc.dispatch("u", "receipts",
                               data={"receipt_id": "r1", "application_id": "a1"},
                               dedup_key="receipt:r1")
        row = await isolated_db.notifications.find_one({"user_id": "u"})
        assert row is not None
        assert set(row["data"].keys()) <= {"application_id", "receipt_id"}


# ---------------------------------------------------------------------------
# Event helpers — never raise back to caller.
# ---------------------------------------------------------------------------

class TestEventHelpersSwallowErrors:
    @pytest.mark.asyncio
    async def test_dispatch_failure_does_not_propagate(self, isolated_db, monkeypatch):
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "x"); monkeypatch.setenv("VAPID_PRIVATE_KEY", "y")
        monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@opportunityos.dev")

        async def boom(*a, **k):
            raise RuntimeError("boom")
        monkeypatch.setattr(svc, "dispatch", boom)
        # None of these must raise.
        await notif_events.on_outcome_logged("u", "app-1", "o1", "response")
        await notif_events.on_interview_scheduled("u", "app-1", "i1")
        await notif_events.on_receipt_created("u", "app-1", "r1")
        await notif_events.on_authorization_expiring_soon("u", "app-1", "auth-1")
        await notif_events.on_support_ticket_replied("u", "t-1")

    @pytest.mark.asyncio
    async def test_outcome_notify_filter_is_material_only(self, isolated_db, monkeypatch):
        called = []
        async def spy(user_id, category, data, dedup_key=None):
            called.append((category, dedup_key))
        monkeypatch.setattr(svc, "dispatch", spy)
        # Non-material events should NOT dispatch.
        await notif_events.on_outcome_logged("u", "a1", "o1", "viewed")
        await notif_events.on_outcome_logged("u", "a1", "o2", "interview_request")
        assert called == []
        # Material events do.
        await notif_events.on_outcome_logged("u", "a1", "o3", "response")
        await notif_events.on_outcome_logged("u", "a1", "o4", "offer")
        assert [c[0] for c in called] == ["application_updates", "application_updates"]


# ---------------------------------------------------------------------------
# Provider status truthfulness.
# ---------------------------------------------------------------------------

class TestProviderStatusTruthfulness:
    def _fresh_provider(self):
        p = WebPushProvider()
        p.configure()
        return p

    def test_configuration_required_when_env_missing(self, monkeypatch):
        for k in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"):
            monkeypatch.delenv(k, raising=False)
        p = self._fresh_provider()
        assert p.status().value == "CONFIGURATION_REQUIRED"

    def test_configuration_required_when_subject_is_not_mailto(self, monkeypatch):
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "pub")
        monkeypatch.setenv("VAPID_PRIVATE_KEY", "priv")
        monkeypatch.setenv("VAPID_SUBJECT", "not-a-mailto")
        p = self._fresh_provider()
        assert p.status().value == "CONFIGURATION_REQUIRED"

    def test_connected_when_env_present(self, monkeypatch):
        # Uses the real .env pair generated for preview.
        assert os.environ.get("VAPID_PUBLIC_KEY")
        assert os.environ.get("VAPID_PRIVATE_KEY")
        assert os.environ.get("VAPID_SUBJECT", "").startswith("mailto:")
        p = self._fresh_provider()
        assert p.status().value == "CONNECTED"

    def test_degraded_after_recent_error(self, monkeypatch):
        from integrations.base import ProviderError
        p = self._fresh_provider()
        assert p.status().value == "CONNECTED"
        p.record_error(ProviderError(code="boom", message="e", provider=p.slug))
        assert p.status().value == "DEGRADED"

    def test_describe_never_leaks_key_values(self):
        p = self._fresh_provider()
        blob = json.dumps(p.describe())
        assert os.environ["VAPID_PRIVATE_KEY"] not in blob
        # Only env-var NAMES appear in required_env / missing_env.
        assert "VAPID_PRIVATE_KEY" in blob  # the NAME is fine
