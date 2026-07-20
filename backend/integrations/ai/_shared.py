"""Shared AI-provider validation — Emergent-LLM-key fallback.

Per the founder mandate: when per-provider OPENAI_API_KEY / ANTHROPIC_API_KEY /
GEMINI_API_KEY is absent but `EMERGENT_LLM_KEY` is set, the adapter reports
`TEST_MODE` with note "Connected (Emergent key)" — v0.1 sandbox path.
"""
from __future__ import annotations

import os
from integrations.base import ConfigValidation


def emergent_llm_key_present() -> bool:
    return bool(os.environ.get("EMERGENT_LLM_KEY", "").strip())


def ai_validate(required_env: tuple[str, ...], config: dict) -> ConfigValidation:
    """Native-key wins; else Emergent-LLM-key fallback → test-mode; else missing."""
    if all(config.get(k) for k in required_env):
        # A real per-provider key is present — treat as production unless
        # further inspection shows a sandbox prefix (adapters override).
        return ConfigValidation(ok=True, is_test_mode=False,
                                 note="Configured with native provider API key.")
    if emergent_llm_key_present():
        return ConfigValidation(ok=True, is_test_mode=True,
                                 note="Connected (Emergent key).")
    return ConfigValidation(ok=False, missing_env=list(required_env),
                             note="Set the native provider API key OR EMERGENT_LLM_KEY.")
