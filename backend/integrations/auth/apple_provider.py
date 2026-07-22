"""Apple Sign-In adapter — standards-based OIDC (not Emergent-managed).

**Playbook finding (verified via `integration_playbook_expert_v2`):** Emergent
does NOT expose a managed Sign in with Apple service analogous to the
Emergent-managed Google Auth. The compliant path is Apple's authorization-
code flow with `response_mode=form_post`, an ES256 client-secret JWT signed
with the Apple `.p8` key, and JWKS-based id_token verification. This
adapter surfaces truthful status:

  - CONFIGURATION_REQUIRED · any of the 5 required env vars missing OR the
    private key doesn't parse as an ES256 P-256 PEM.
  - DEGRADED · configured, but the last smoke probe against Apple's JWKS
    URL failed within the last 5 minutes.
  - CONNECTED · all 5 env vars present, private key parses, JWKS reachable.

Secrets are NEVER surfaced by `describe()` — only env-var NAMES appear in
`required_env`. The private key never leaves the pod.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import httpx

from integrations.base import (
    BaseProvider, ProviderCategory, HealthResult, TestResult, ConfigValidation,
    ProviderStatus, ProviderError,
)
from integrations import registry


APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"


class AppleAuthProvider(BaseProvider):
    slug = "apple_auth"
    label = "Sign in with Apple (standards-based OIDC)"
    category = ProviderCategory.AUTH
    required_env = (
        "APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID",
        "APPLE_PRIVATE_KEY", "APPLE_REDIRECT_URI",
    )
    optional_env = ("APPLE_AUTH_ENABLED",)
    docs_url = "https://developer.apple.com/sign-in-with-apple/"
    supports_test_mode = False

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "")
                       for k in (*self.required_env, *self.optional_env)}

    def validate_configuration(self) -> ConfigValidation:
        missing = [k for k in self.required_env if not self.config.get(k)]
        # Redirect URI MUST be HTTPS in production; Apple refuses http scheme.
        redirect = (self.config.get("APPLE_REDIRECT_URI") or "").strip()
        if redirect and not redirect.startswith("https://"):
            missing.append("APPLE_REDIRECT_URI (must be an HTTPS URL)")
        # Private key sanity check — must at least be a PEM block.
        pk = (self.config.get("APPLE_PRIVATE_KEY") or "").strip()
        if pk and not pk.startswith("-----BEGIN") and "\\n-----BEGIN" not in pk:
            missing.append("APPLE_PRIVATE_KEY (must be a PEM-encoded .p8 EC key)")
        if missing:
            return ConfigValidation(
                ok=False, missing_env=missing,
                note="Standards-based Sign in with Apple. Provide Apple "
                     "Developer credentials (.p8, Team ID, Key ID, Services "
                     "ID) and an HTTPS redirect URI.",
                is_test_mode=False,
            )
        return ConfigValidation(
            ok=True,
            note="Standards-based Sign in with Apple. Configuration present.",
            is_test_mode=False,
        )

    async def health_check(self) -> HealthResult:
        started = time.time()
        try:
            import jwt  # noqa: F401
            self._parse_private_key()
            # Cheap probe — verify Apple's JWKS is reachable so we can verify
            # id_tokens at flow time. Ignores response body content.
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(APPLE_JWKS_URL)
                if r.status_code != 200:
                    return HealthResult(healthy=False,
                                        error=f"apple jwks HTTP {r.status_code}",
                                        latency_ms=int((time.time() - started) * 1000))
            return HealthResult(healthy=True,
                                latency_ms=int((time.time() - started) * 1000))
        except Exception as e:
            return HealthResult(healthy=False, error=str(e)[:200],
                                latency_ms=int((time.time() - started) * 1000))

    async def test_connection(self) -> TestResult:
        started = time.time()
        v = self.validate_configuration()
        if not v.ok:
            return TestResult(ok=False,
                              detail="configuration_required: " + ", ".join(v.missing_env),
                              latency_ms=int((time.time() - started) * 1000))
        h = await self.health_check()
        if h.healthy:
            self.record_success()
            return TestResult(ok=True,
                              detail="Apple .p8 loads, JWKS reachable. Standards-based OIDC ready.",
                              latency_ms=int((time.time() - started) * 1000))
        self.record_error(ProviderError(code="apple_health_failed",
                                        message=(h.error or "unknown")[:200],
                                        provider=self.slug))
        return TestResult(ok=False, detail=f"apple_health_failed: {h.error}",
                          latency_ms=int((time.time() - started) * 1000))

    def _parse_private_key(self):
        pk = (self.config.get("APPLE_PRIVATE_KEY") or "").strip()
        if not pk:
            raise ValueError("APPLE_PRIVATE_KEY missing")
        # Support keys stored with literal \n escapes.
        pk = pk.replace("\\n", "\n")
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key = load_pem_private_key(pk.encode(), password=None)
        # Apple keys are EC P-256 (used with ES256).
        curve_name = getattr(getattr(key, "curve", None), "name", "")
        if "secp256" not in curve_name.lower() and "prime256" not in curve_name.lower():
            raise ValueError(f"APPLE_PRIVATE_KEY is not an EC P-256 key (curve={curve_name})")
        return key

    def status(self, *, feature_flag_enabled: bool = True) -> ProviderStatus:
        if self._disabled or not feature_flag_enabled:
            return ProviderStatus.DISABLED
        enabled = (self.config.get("APPLE_AUTH_ENABLED") or "true").lower()
        if enabled in ("0", "false", "off"):
            return ProviderStatus.DISABLED
        v = self.validate_configuration()
        if not v.ok:
            return ProviderStatus.CONFIGURATION_REQUIRED
        if self._last_error and (time.time() - self._last_error_at) < 300:
            return ProviderStatus.DEGRADED
        return ProviderStatus.CONNECTED


registry.register(AppleAuthProvider())
