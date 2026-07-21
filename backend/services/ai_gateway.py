"""AI gateway — unified `chat()` surface over the provider registry.

Strangler pattern:
    - `services/llm.py` remains the canonical LLM path in v0.1 (used by resume
      parsing + tailoring). It is untouched here.
    - The new gateway is a thin router: pick a provider adapter, delegate to
      its `chat()`, record cost. When parity tests are green a future patch
      swaps `services/llm.py` to call `ai_gateway.chat(...)` and the emergent
      SDK dependency can be retired.

All calls hard-fail with `ProviderError("configuration_required", ...)` when
the selected provider is unconfigured. No bypass.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from core.db import get_db
from core.time_utils import utc_now
from integrations import registry
from integrations.base import ProviderError


log = logging.getLogger("oppos.ai_gateway")


# Public price cards — mirror `services/llm.py` for consistent ledger rows.
_PRICE_TABLE_PER_1K = {
    "gpt-5":    {"in": 0.00500, "out": 0.01500, "source": "openai:public_2026-02"},
    "gpt-4o":   {"in": 0.00250, "out": 0.01000, "source": "openai:public_2026-02"},
    "claude-sonnet-4-5-20250929": {"in": 0.00300, "out": 0.01500, "source": "anthropic:public_2026-02"},
    "claude-sonnet-4-6":          {"in": 0.00300, "out": 0.01500, "source": "anthropic:public_2026-02"},
    "gemini-2.0-flash":           {"in": 0.00010, "out": 0.00040, "source": "gemini:public_2026-02"},
}


@dataclass
class ChatResult:
    provider: str
    model: str
    raw: str
    tokens_in_est: int
    tokens_out_est: int
    cost_usd_est: float
    session_id: str


def _rough_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def _prompt_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


async def _record_cost(*, user_id: str | None, task: str, provider: str,
                          model: str, tokens_in: int, tokens_out: int,
                          session_id: str, outcome: str = "success",
                          extra: dict[str, Any] | None = None) -> float:
    card = _PRICE_TABLE_PER_1K.get(model, {"in": 0.0, "out": 0.0, "source": "unknown_model"})
    cost = (tokens_in / 1000.0) * card["in"] + (tokens_out / 1000.0) * card["out"]
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id, "task": task,
        "model": model, "provider": provider,
        "tokens_in_est": int(tokens_in), "tokens_out_est": int(tokens_out),
        "cost_usd_est": round(cost, 6),
        "price_source": card.get("source"),
        "session_id": session_id, "ts": utc_now(),
        "extra": {"outcome": outcome, **(extra or {})},
        "gateway": "ai_gateway.v1",
    }
    try:
        await get_db().llm_costs.insert_one(row)
    except Exception:
        log.exception("Failed to persist llm_costs row via gateway")
    return cost


async def chat(*, provider_slug: str, model: str, system: str, user_message: str,
                 task: str, user_id: str | None = None,
                 session_id: str | None = None,
                 extra: dict[str, Any] | None = None) -> ChatResult:
    """Route a single-turn chat call through the registry's AI adapter.

    Adapters must implement `chat(model, system, user_message, session_id) →
    (raw_text, tokens_in_est, tokens_out_est)`. Fabrication guarantees remain
    the caller's responsibility; the gateway does NOT alter the prompt.
    """
    provider = registry.get(provider_slug)
    if provider is None or getattr(provider, "category", None) is None \
            or provider.category.value != "ai":
        raise ProviderError("unknown_ai_provider", f"no AI adapter for slug={provider_slug}",
                              provider=provider_slug)
    if not hasattr(provider, "chat"):
        raise ProviderError("chat_not_supported", f"{provider_slug} does not implement chat()",
                              provider=provider_slug)
    session_id = session_id or f"{task}-{uuid.uuid4().hex[:8]}"
    try:
        raw, tokens_in, tokens_out = await provider.chat(  # type: ignore[attr-defined]
            model=model, system=system, user_message=user_message,
            session_id=session_id,
        )
    except ProviderError as e:
        await _record_cost(user_id=user_id, task=task, provider=provider_slug,
                             model=model,
                             tokens_in=_rough_tokens(system + user_message),
                             tokens_out=0, session_id=session_id,
                             outcome="failed",
                             extra={**(extra or {}), "error": e.code})
        raise
    except Exception as e:
        err = ProviderError("chat_error", str(e)[:200], provider=provider_slug, retryable=True)
        await _record_cost(user_id=user_id, task=task, provider=provider_slug,
                             model=model,
                             tokens_in=_rough_tokens(system + user_message),
                             tokens_out=0, session_id=session_id,
                             outcome="failed",
                             extra={**(extra or {}), "error": str(e)[:200]})
        raise err

    cost = await _record_cost(user_id=user_id, task=task, provider=provider_slug,
                                model=model, tokens_in=tokens_in, tokens_out=tokens_out,
                                session_id=session_id, outcome="success", extra=extra)
    return ChatResult(provider=provider_slug, model=model, raw=raw,
                       tokens_in_est=tokens_in, tokens_out_est=tokens_out,
                       cost_usd_est=cost, session_id=session_id)
