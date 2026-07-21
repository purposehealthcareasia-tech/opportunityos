"""OpenAI provider adapter — Milestone G.

`chat()` delegates to the shared Emergent-LLM-key path for uniform cost
recording and key management. Native `OPENAI_API_KEY` is still surfaced as
`required_env` for operators who want to switch to a direct account.
"""
from __future__ import annotations

import os
import time

from integrations.base import (
    BaseProvider, ProviderCategory, ConfigValidation, HealthResult, TestResult,
)
from integrations import registry
from integrations.ai._shared import (
    ai_validate, emergent_llm_key_present, emergent_chat_singleturn,
)


class OpenAIProvider(BaseProvider):
    slug = "openai"
    label = "OpenAI"
    category = ProviderCategory.AI
    required_env = ("OPENAI_API_KEY",)
    optional_env = ("EMERGENT_LLM_KEY",)
    docs_url = "https://platform.openai.com/api-keys"
    supports_test_mode = True
    _emergent_provider_slug = "openai"

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
        # Cheap: assert the SDK is importable + key looks non-empty.
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


registry.register(OpenAIProvider())
