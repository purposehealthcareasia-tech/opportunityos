"""Milestone G — AI gateway + adapter chat() regression.

Coverage:
  1. `ai_gateway.chat()` routes to the correct provider adapter.
  2. Cost row is persisted to `llm_costs` on success + failure.
  3. Adapter `chat()` hard-fails when `EMERGENT_LLM_KEY` is unset.
  4. Unknown / non-AI slug raises `unknown_ai_provider`.
  5. Adapter surface never bypasses the shared `emergent_chat_singleturn`
     helper — enforced by stubbing that single function and asserting the
     gateway routes through it.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from pymongo import MongoClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "opportunityos")


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_registry():
    from integrations import registry
    registry.load_all()
    yield


@pytest.fixture
def sync_db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def _run(coro):
    from core import db as db_mod
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        try:
            db_mod._client = None  # type: ignore[attr-defined]
            db_mod._db = None      # type: ignore[attr-defined]
        except Exception:
            pass


class TestAIGatewayRouting:
    def test_routes_to_openai_and_records_cost(self, monkeypatch, sync_db):
        """Stubbing the shared emergent helper proves BOTH the OpenAI adapter
        AND the gateway route through the single documented I/O boundary."""
        from integrations.ai import _shared as ai_shared
        from services import ai_gateway

        async def _stub(*, provider, model, system, user_message, session_id):
            assert provider == "openai"
            assert session_id
            return ("STUBBED_OPENAI_REPLY", 42, 17)

        monkeypatch.setattr(ai_shared, "emergent_chat_singleturn", _stub)
        # The adapter imports the helper by name at module load — patch it
        # inside the provider module too so the alias points at the stub.
        from integrations.ai import openai_provider as adapter_module
        monkeypatch.setattr(adapter_module, "emergent_chat_singleturn", _stub)

        sess = f"gateway-test-{uuid.uuid4().hex[:8]}"
        result = _run(ai_gateway.chat(
            provider_slug="openai", model="gpt-5",
            system="you are a test", user_message="ping",
            task="test_chat", user_id="u-test", session_id=sess,
        ))
        assert result.raw == "STUBBED_OPENAI_REPLY"
        assert result.tokens_in_est == 42
        assert result.tokens_out_est == 17
        # Cost row persisted.
        row = sync_db.llm_costs.find_one({"session_id": sess})
        assert row is not None
        assert row["provider"] == "openai"
        assert row["model"] == "gpt-5"
        assert row["gateway"] == "ai_gateway.v1"
        assert row["extra"]["outcome"] == "success"
        sync_db.llm_costs.delete_one({"session_id": sess})

    def test_records_cost_on_failure(self, monkeypatch, sync_db):
        from integrations.ai import _shared as ai_shared
        from integrations.ai import anthropic_provider as adapter_module
        from services import ai_gateway
        from integrations.base import ProviderError

        async def _stub_fail(*, provider, model, system, user_message, session_id):
            raise RuntimeError("upstream_boom")

        monkeypatch.setattr(ai_shared, "emergent_chat_singleturn", _stub_fail)
        monkeypatch.setattr(adapter_module, "emergent_chat_singleturn", _stub_fail)

        sess = f"gateway-fail-{uuid.uuid4().hex[:8]}"
        with pytest.raises(ProviderError):
            _run(ai_gateway.chat(
                provider_slug="anthropic", model="claude-sonnet-4-6",
                system="s", user_message="u",
                task="test_chat_fail", user_id="u-test", session_id=sess,
            ))
        row = sync_db.llm_costs.find_one({"session_id": sess})
        assert row is not None
        assert row["extra"]["outcome"] == "failed"
        sync_db.llm_costs.delete_one({"session_id": sess})


class TestAdapterHardFail:
    def test_openai_chat_hardfails_without_emergent_key(self, monkeypatch):
        from integrations import registry
        from integrations.base import ProviderError
        # Force the shared helper to see an empty key by patching os.environ
        # inside the helper's namespace.
        from integrations.ai import _shared as ai_shared
        monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
        provider = registry.get("openai")
        with pytest.raises(ProviderError) as ei:
            _run(provider.chat(
                model="gpt-5", system="s", user_message="u",
                session_id="hardfail-" + uuid.uuid4().hex,
            ))
        assert ei.value.code == "configuration_required"


class TestGatewayUnknownProvider:
    def test_unknown_slug_raises(self):
        from services import ai_gateway
        from integrations.base import ProviderError
        with pytest.raises(ProviderError) as ei:
            _run(ai_gateway.chat(
                provider_slug="not_a_real_slug", model="x",
                system="s", user_message="u", task="t",
            ))
        assert ei.value.code == "unknown_ai_provider"

    def test_non_ai_slug_raises(self):
        """Stripe is a payments adapter — the gateway must refuse it."""
        from services import ai_gateway
        from integrations.base import ProviderError
        with pytest.raises(ProviderError) as ei:
            _run(ai_gateway.chat(
                provider_slug="stripe", model="x",
                system="s", user_message="u", task="t",
            ))
        assert ei.value.code == "unknown_ai_provider"
