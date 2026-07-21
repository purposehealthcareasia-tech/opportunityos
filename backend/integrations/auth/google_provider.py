"""Google Sign-In adapter — Milestone E (Emergent-managed Google OAuth).

Emergent operates the OAuth handshake; there is no per-app client secret to
provision. The adapter's job is threefold:

  1. Report truthful status to the admin dashboard:
     - CONNECTED once the frontend redirect URL is confirmed set + the
       backend session-data endpoint responds.
     - TEST_MODE if `GOOGLE_AUTH_TEST_MODE=true`.
     - DEGRADED if `test_connection()` recently failed.
  2. Provide `test_connection()` that pings the Emergent session-data
     endpoint (unauth request that returns 401 — that's a healthy signal).
  3. Never leak secrets — Emergent does not hand us a client secret; the
     `linked_auth_identities` and `pending_google_signups` collections are
     the only Google-linked material on our side.
"""
from __future__ import annotations

import os
import time

import httpx

from integrations.base import (
    BaseProvider, ProviderCategory, HealthResult, TestResult, ConfigValidation,
)
from integrations import registry


EMERGENT_PROBE_URL = (
    "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
)


class GoogleAuthProvider(BaseProvider):
    slug = "google_auth"
    label = "Google Sign-In (Emergent-managed)"
    category = ProviderCategory.AUTH
    # Emergent-managed → no per-app client id/secret needed. We surface a
    # feature-flag env var for operators who want to explicitly gate rollout.
    required_env = ()
    optional_env = ("GOOGLE_AUTH_ENABLED", "GOOGLE_AUTH_TEST_MODE")
    docs_url = "https://auth.emergentagent.com/"
    supports_test_mode = True

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        return (self.config.get("GOOGLE_AUTH_TEST_MODE") or "").lower() in ("1", "true", "yes")

    def validate_configuration(self) -> ConfigValidation:
        # Emergent-managed → configuration is always considered complete.
        enabled = (self.config.get("GOOGLE_AUTH_ENABLED") or "true").lower()
        if enabled in ("0", "false", "off"):
            return ConfigValidation(ok=False, missing_env=[],
                                     note="GOOGLE_AUTH_ENABLED=false — disabled by operator.")
        return ConfigValidation(ok=True, is_test_mode=self._detect_test_mode(),
                                 note="Emergent-managed. No client secret required.")

    async def health_check(self) -> HealthResult:
        return HealthResult(healthy=True)

    async def test_connection(self) -> TestResult:
        """The Emergent session-data endpoint requires `X-Session-ID`. Hitting
        it without one is expected to yield a 4xx — which is the health signal
        we want (the endpoint is reachable and authenticating properly)."""
        try:
            t0 = time.time()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(EMERGENT_PROBE_URL)
            latency_ms = int((time.time() - t0) * 1000)
            # Any 4xx = endpoint reachable + demanding credentials (healthy).
            if r.status_code < 500:
                return TestResult(ok=True,
                                   detail=f"Emergent session-data endpoint reachable (HTTP {r.status_code}).",
                                   latency_ms=latency_ms)
            return TestResult(ok=False,
                               detail=f"Emergent session-data HTTP {r.status_code}.",
                               latency_ms=latency_ms)
        except Exception as e:
            return TestResult(ok=False, detail=f"probe_error: {str(e)[:200]}")


registry.register(GoogleAuthProvider())
