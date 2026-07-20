"""Google Gemini provider adapter — Milestone A stub.

Adapter registered so the admin Integrations dashboard shows honest
CONFIGURATION_REQUIRED status until real credentials + full flow arrive
in the milestone that owns this category. Deep implementation:
Milestone E — AI gateway."""
from __future__ import annotations

import os
from integrations.base import (
    BaseProvider, ProviderCategory, HealthResult, TestResult,
)
from integrations import registry


class GeminiProvider(BaseProvider):
    slug = "gemini"
    label = "Google Gemini"
    category = ProviderCategory.AI
    required_env = ('GEMINI_API_KEY',)
    optional_env = ('EMERGENT_LLM_KEY',)
    docs_url = "https://aistudio.google.com/apikey"
    supports_test_mode = True

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def validate_configuration(self):
        from integrations.ai._shared import ai_validate
        return ai_validate(self.required_env, self.config)

    async def health_check(self) -> HealthResult:
        v = self.validate_configuration()
        return HealthResult(healthy=v.ok, error=None if v.ok else v.note)

    async def test_connection(self) -> TestResult:
        from integrations.ai._shared import emergent_llm_key_present
        native = self.required_env[0]
        if self.config.get(native):
            return TestResult(ok=True, detail=f"{native} present. Deep probe deferred to Milestone E.")
        if emergent_llm_key_present():
            return TestResult(ok=True, detail="Emergent LLM key present. Deep probe deferred to Milestone E.")
        return TestResult(ok=False, detail=f"CONFIGURATION_REQUIRED — set {native} or EMERGENT_LLM_KEY.")


registry.register(GeminiProvider())
