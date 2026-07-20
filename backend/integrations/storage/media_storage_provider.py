"""Media storage provider adapter — Milestone A stub.

Adapter registered so the admin Integrations dashboard shows honest
CONFIGURATION_REQUIRED status until real credentials + full flow arrive
in the milestone that owns this category. Deep implementation:
Milestone G — Storage + ElevenLabs."""
from __future__ import annotations

import os
from integrations.base import (
    BaseProvider, ProviderCategory, HealthResult, TestResult,
)
from integrations import registry


class MediaStorageProvider(BaseProvider):
    slug = "media_storage"
    label = "Media storage"
    category = ProviderCategory.STORAGE
    required_env = ()
    optional_env = ('MEDIA_STORAGE_BACKEND',)
    docs_url = ""
    supports_test_mode = False

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        # Overridden per-provider once real credentials arrive.
        return bool(self.config)

    async def health_check(self) -> HealthResult:
        missing = [k for k in self.required_env if not self.config.get(k)]
        if missing:
            return HealthResult(healthy=False, error=f"env vars missing: {missing}")
        return HealthResult(healthy=True)

    async def test_connection(self) -> TestResult:
        missing = [k for k in self.required_env if not self.config.get(k)]
        if missing:
            return TestResult(ok=False,
                              detail=f"CONFIGURATION_REQUIRED — set: {', '.join(missing)}")
        return TestResult(ok=True,
                          detail="Configured. Full test-connection lands in the deep-implementation milestone.")


registry.register(MediaStorageProvider())
