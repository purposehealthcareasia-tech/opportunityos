"""LYNK Collider readiness in Fynd's existing audited admin dashboard.

This adapter can probe a configured engine, not launch scans. No run routes,
global evidence access, job ingestion, billing, or application submission are
enabled here. Source policy propagation and tenant isolation remain prerequisites.
"""
from __future__ import annotations

import os
import time

from domains.collider.client import (
    ColliderClient, ColliderConfigurationError, ColliderError,
    validate_configuration as validate_client_configuration,
)
from integrations import registry
from integrations.base import (
    BaseProvider, ConfigValidation, HealthResult, ProviderCategory,
    ProviderError, ProviderStatus, TestResult,
)


class ColliderProvider(BaseProvider):
    slug = "lynk_collider"
    label = "LYNK Collider (connection only)"
    category = ProviderCategory.DISCOVERY
    required_env = ("FYND_COLLIDER_BASE_URL", "FYND_COLLIDER_TOKEN")
    optional_env = ("FYND_COLLIDER_ENABLED",)
    CHECK_TTL_SECONDS = 300

    def configure(self) -> None:
        self.config = {
            k: os.environ.get(k, "")
            for k in (*self.required_env, *self.optional_env)
        }
        self._last_success_at = 0.0
        self._last_error = None
        self._last_error_at = 0.0

    def _probe_enabled(self) -> bool:
        return self.config.get("FYND_COLLIDER_ENABLED", "").strip().lower() == "true"

    def validate_configuration(self) -> ConfigValidation:
        missing = [key for key in self.required_env if not self.config.get(key)]
        if missing:
            return ConfigValidation(ok=False, missing_env=missing,
                                    note="Private engine configuration is required. Scanning remains locked.")
        try:
            validate_client_configuration(self.config[self.required_env[0]],
                                          self.config[self.required_env[1]])
        except ColliderConfigurationError:
            return ConfigValidation(ok=False,
                                    note="Invalid private engine configuration; check the server origin and token.")
        return ConfigValidation(ok=True, note="Connection checks only. User scans are not enabled.")

    def status(self, *, feature_flag_enabled: bool = True) -> ProviderStatus:
        if self._disabled or not feature_flag_enabled:
            return ProviderStatus.DISABLED
        if not self.validate_configuration().ok:
            return ProviderStatus.CONFIGURATION_REQUIRED
        if not self._probe_enabled():
            return ProviderStatus.DISABLED
        # Credentials alone never mean connected. An expired probe is stale,
        # not evidence that a private service is still reachable.
        if (self._last_error or not self._last_success_at
                or time.time() - self._last_success_at > self.CHECK_TTL_SECONDS):
            return ProviderStatus.DEGRADED
        return ProviderStatus.CONNECTED

    async def test_connection(self) -> TestResult:
        validation = self.validate_configuration()
        if not validation.ok:
            return TestResult(ok=False, detail=validation.note)
        if self._disabled or not self._probe_enabled():
            return TestResult(ok=False, detail="Connection probes are disabled. No scan was started.")
        started = time.monotonic()
        try:
            async with ColliderClient(
                self.config["FYND_COLLIDER_BASE_URL"],
                self.config["FYND_COLLIDER_TOKEN"],
                timeout_seconds=5,
                max_response_bytes=262144,
            ) as client:
                await client.health()
                await client.capabilities()
            self.record_success()
            return TestResult(
                ok=True,
                detail="Private gateway and capability contract verified. This does not verify scraping providers. User scans remain locked.",
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except (ColliderError, ColliderConfigurationError):
            # No upstream body, URL, token, or raw exception reaches the admin
            # event store (the existing router persists TestResult.detail).
            self.record_error(ProviderError(
                "connection_unverified", "Private Collider connection could not be verified.",
                provider=self.slug, retryable=True,
            ))
            return TestResult(ok=False, detail="Private Collider connection could not be verified. No scan was started.",
                              latency_ms=int((time.monotonic() - started) * 1000))

    async def health_check(self) -> HealthResult:
        # Snapshotting providers must not perform network activity at boot.
        connected = self.status() == ProviderStatus.CONNECTED
        return HealthResult(healthy=connected,
                            error=None if connected else "Connection has not been recently verified.")

    def describe(self) -> dict:
        result = super().describe()
        result.update({
            "integration_note": self.validate_configuration().note,
            "rollout_stage": "connection_only",
            "scan_enabled": False,
            "application_submission_enabled": False,
            "internet_coverage_percent": None,
            "connection_probe_enabled": self._probe_enabled() and not self._disabled,
            "readiness_blockers": [
                "Private hosted engine with persistent storage",
                "Per-user run and evidence isolation",
                "Fynd source policy enforced at every network hop",
                "Budgets, retention, deletion, and licensing review",
            ],
        })
        return result


registry.register(ColliderProvider())
