"""Shared AI-provider primitives.

- `ai_validate` — status validation with EMERGENT_LLM_KEY fallback.
- `emergent_llm_key_present` — pod-level key check.
- `emergent_chat_singleturn` — the canonical single-turn call. Wraps
  `emergentintegrations.llm.chat.LlmChat` and returns
  `(raw_text, tokens_in_est, tokens_out_est)`.

Every AI adapter (openai / anthropic / gemini) delegates to
`emergent_chat_singleturn` for actual model I/O so we have exactly ONE
code path talking to the vendor SDK.
"""
from __future__ import annotations

import os
from typing import Tuple

from integrations.base import ConfigValidation, ProviderError


def emergent_llm_key_present() -> bool:
    return bool(os.environ.get("EMERGENT_LLM_KEY", "").strip())


def ai_validate(required_env: tuple[str, ...], config: dict) -> ConfigValidation:
    """Native-key wins; else Emergent-LLM-key fallback → test-mode; else missing."""
    if all(config.get(k) for k in required_env):
        return ConfigValidation(ok=True, is_test_mode=False,
                                 note="Configured with native provider API key.")
    if emergent_llm_key_present():
        return ConfigValidation(ok=True, is_test_mode=True,
                                 note="Connected (Emergent key).")
    return ConfigValidation(ok=False, missing_env=list(required_env),
                             note="Set the native provider API key OR EMERGENT_LLM_KEY.")


def _rough_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


async def emergent_chat_singleturn(*, provider: str, model: str,
                                      system: str, user_message: str,
                                      session_id: str) -> Tuple[str, int, int]:
    """Single-turn LLM call via the Emergent LLM key.

    Returns `(raw_text, tokens_in_est, tokens_out_est)`. Hard-fails with
    `ProviderError` when `EMERGENT_LLM_KEY` is not set.
    """
    key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        raise ProviderError("configuration_required",
                              "EMERGENT_LLM_KEY not set", provider=provider)
    # Local import — the SDK is only required when we actually chat.
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(api_key=key, session_id=session_id,
                    system_message=system).with_model(provider, model)
    raw = await chat.send_message(UserMessage(text=user_message))
    raw_text = raw if isinstance(raw, str) else str(raw or "")
    return raw_text, _rough_tokens(system + user_message), _rough_tokens(raw_text)
