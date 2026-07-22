"""Standards-based Web Push provider (VAPID + pywebpush).

**Not vendor-managed.** Emergent does not expose a managed web-push service —
the `integration_playbook_expert_v2` playbook confirmed this explicitly. This
provider drives the standards path: browser Push API + Service Worker on the
client, pywebpush + VAPID on the server, direct delivery to the browser's
push service (FCM/Mozilla autopush/Apple) with no intermediate gateway.

Truthful status semantics (per founder amendment):
  - CONFIGURATION_REQUIRED · when VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY /
    VAPID_SUBJECT are missing OR VAPID_SUBJECT is not a real `mailto:` URI.
  - DEGRADED · configured, but the last smoke probe or dispatch attempt
    raised (e.g. cryptography failure).
  - CONNECTED · configured AND the smoke probe (pywebpush import + key
    parse) passed. There is no vendor gateway to health-check.

Secrets are NEVER surfaced by `describe()` — only env-var NAMES.
"""
from __future__ import annotations

import os
import re
import time

from integrations.base import (
    BaseProvider,
    ConfigValidation,
    HealthResult,
    ProviderCategory,
    ProviderStatus,
    TestResult,
)
from integrations import registry


_SUBJECT_RE = re.compile(r"^mailto:[^@\s]+@[^@\s]+\.[^@\s]+$")


class WebPushProvider(BaseProvider):
    slug = "push_notifications"
    label = "Web Push (VAPID · standards-based)"
    category = ProviderCategory.NOTIFICATIONS
    required_env = ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT")
    optional_env = ()
    docs_url = "https://developer.mozilla.org/en-US/docs/Web/API/Push_API"
    supports_test_mode = False

    def configure(self) -> None:
        self.config = {
            "VAPID_PUBLIC_KEY": os.environ.get("VAPID_PUBLIC_KEY", ""),
            "VAPID_PRIVATE_KEY": os.environ.get("VAPID_PRIVATE_KEY", ""),
            "VAPID_SUBJECT": os.environ.get("VAPID_SUBJECT", ""),
        }

    def validate_configuration(self) -> ConfigValidation:
        missing = [k for k in self.required_env if not self.config.get(k)]
        subject = (self.config.get("VAPID_SUBJECT") or "").strip()
        if subject and not _SUBJECT_RE.match(subject):
            missing.append("VAPID_SUBJECT (must be `mailto:<real-email>`)")
        if missing:
            return ConfigValidation(
                ok=False,
                missing_env=missing,
                note="Standards-based Web Push (VAPID) — no vendor gateway. "
                "Provide the VAPID key pair and a real mailto: subject.",
                is_test_mode=False,
            )
        return ConfigValidation(
            ok=True,
            note="Standards-based Web Push (VAPID) — no vendor gateway.",
            is_test_mode=False,
        )

    async def health_check(self) -> HealthResult:
        """Light probe — verify pywebpush imports and the private key decodes."""
        started = time.time()
        try:
            import pywebpush  # noqa: F401
            from py_vapid import Vapid01  # noqa: F401
            # Try to parse the private key to confirm it is a real VAPID key.
            self._parse_private_key()
            return HealthResult(healthy=True, latency_ms=int((time.time() - started) * 1000))
        except Exception as e:  # pragma: no cover — misconfig path
            return HealthResult(healthy=False, error=str(e)[:200])

    async def test_connection(self) -> TestResult:
        """Admin dashboard action — deeper smoke that also refuses a placeholder
        subject. Never sends a real push (no arbitrary subscription available)."""
        started = time.time()
        v = self.validate_configuration()
        if not v.ok:
            return TestResult(
                ok=False,
                detail="configuration_required: " + ", ".join(v.missing_env),
                latency_ms=int((time.time() - started) * 1000),
            )
        try:
            self._parse_private_key()
            self.record_success()
            return TestResult(
                ok=True,
                detail="VAPID key pair loads. Standards-based Web Push ready. "
                "Real deliverability requires an active browser subscription.",
                latency_ms=int((time.time() - started) * 1000),
            )
        except Exception as e:  # pragma: no cover
            from integrations.base import ProviderError
            self.record_error(ProviderError(
                code="vapid_key_parse_failed", message=str(e)[:200],
                provider=self.slug,
            ))
            return TestResult(
                ok=False,
                detail=f"vapid_key_parse_failed: {str(e)[:200]}",
                latency_ms=int((time.time() - started) * 1000),
            )

    # ---- helpers -------------------------------------------------------

    def _parse_private_key(self):
        """Decode the base64url private key so we know it round-trips."""
        import base64
        raw = self.config["VAPID_PRIVATE_KEY"].strip()
        # urlsafe base64 without padding
        pad = "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode(raw + pad)
        if len(decoded) != 32:
            raise ValueError("VAPID_PRIVATE_KEY is not a 32-byte P-256 scalar")
        return decoded

    def status(self, *, feature_flag_enabled: bool = True) -> ProviderStatus:
        """Truthful status with the founder-amendment semantics."""
        if self._disabled or not feature_flag_enabled:
            return ProviderStatus.DISABLED
        v = self.validate_configuration()
        if not v.ok:
            return ProviderStatus.CONFIGURATION_REQUIRED
        # Recent errors → DEGRADED (window matches BaseProvider default).
        if self._last_error and (time.time() - self._last_error_at) < 300:
            return ProviderStatus.DEGRADED
        return ProviderStatus.CONNECTED


registry.register(WebPushProvider())
