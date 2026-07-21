"""Anthropic Claude provider adapter — Milestone G."""
from __future__ import annotations

import os
import time

from integrations.base import (
    BaseProvider, ProviderCategory, HealthResult, TestResult, ConfigValidation,
)
from integrations import registry
from integrations.ai._shared import (
    ai_validate, emergent_chat_singleturn,
)


class AnthropicProvider(BaseProvider):
    slug = "anthropic"
    label = "Anthropic Claude"
    category = ProviderCategory.AI
    required_env = ("ANTHROPIC_API_KEY",)
    optional_env = ("EMERGENT_LLM_KEY",)
    docs_url = "https://console.anthropic.com/settings/keys"
    supports_test_mode = True
    _emergent_provider_slug = "anthropic"

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def validate_configuration(self) -> ConfigValidation:
        return ai_validate(self.required_env, self.config)

    async def health_check(self) -> HealthResult:
        v = self.validate_configuration()
        return HealthResult(healthy=v.ok, error=None if v.ok else v.note)

    async def test_connection(self) -> TestResult:
        v = self.validate_configuration()
        if not v.ok:
            return TestResult(ok=False, detail=v.note)
        t0 = time.time()
        try:
            from emergentintegrations.llm.chat import LlmChat  # noqa: F401
        except Exception as e:
            return TestResult(ok=False, detail=f"sdk_import_failed: {e}")
        return TestResult(ok=True, detail="AI adapter ready (SDK loaded).",
                           latency_ms=int((time.time() - t0) * 1000))

    async def chat(self, *, model: str, system: str, user_message: str,
                     session_id: str):
        return await emergent_chat_singleturn(
            provider=self._emergent_provider_slug, model=model,
            system=system, user_message=user_message, session_id=session_id,
        )


registry.register(AnthropicProvider())
