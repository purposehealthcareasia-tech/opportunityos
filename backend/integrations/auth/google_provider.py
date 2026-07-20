"""Google OAuth via Emergent-managed integration.

Full implementation lands in Milestone B (behind the integration playbook
recipe). Milestone A just registers the provider so the admin dashboard shows
honest status."""
from __future__ import annotations

import os
from integrations.base import BaseProvider, ProviderCategory, HealthResult, TestResult
from integrations import registry


class GoogleAuthProvider(BaseProvider):
    slug = "google_auth"
    label = "Google (Emergent-managed)"
    category = ProviderCategory.AUTH
    required_env = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")
    optional_env = ("EMERGENT_AUTH_ENABLED",)
    docs_url = "https://console.cloud.google.com/apis/credentials"
    supports_test_mode = True

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in
                        (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        # Emergent-managed flow does not use per-tenant client IDs; treat as
        # sandbox until we wire real prod credentials.
        return True

    async def health_check(self) -> HealthResult:
        if not all(self.config.get(k) for k in self.required_env):
            return HealthResult(healthy=False, error="Google OAuth env not set (Milestone B).")
        return HealthResult(healthy=True)

    async def test_connection(self) -> TestResult:
        return TestResult(
            ok=False,
            detail="Google OAuth adapter is a stub in Milestone A. Full flow lands in Milestone B via integration_playbook_expert_v2.",
        )


registry.register(GoogleAuthProvider())
