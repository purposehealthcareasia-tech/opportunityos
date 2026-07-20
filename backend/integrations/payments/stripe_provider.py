"""Stripe provider adapter.

v0.1 status: TEST_MODE via `emergentintegrations.payments.stripe.checkout`.
This adapter is intentionally a THIN wrapper around the existing
`domains/billing/service.py` — Milestone A does not touch the existing
endpoints. The full payment abstraction (create_checkout / refund /
list_invoices etc. exposed uniformly) lands in Milestone C.

Milestone A responsibilities:
  - Register Stripe with the integration registry so admin dashboard
    shows real status (TEST_MODE if STRIPE_API_KEY looks like a test key,
    CONFIGURATION_REQUIRED otherwise).
  - Provide health_check + test_connection that verify the SDK can
    initialise + does not error on a trivial call.
"""
from __future__ import annotations

import os
import time

from integrations.base import (
    BaseProvider, ProviderCategory, ConfigValidation, HealthResult, TestResult,
    ProviderError,
)
from integrations import registry


class StripeProvider(BaseProvider):
    slug = "stripe"
    label = "Stripe"
    category = ProviderCategory.PAYMENTS
    required_env = ("STRIPE_API_KEY",)
    optional_env = ("STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET")
    docs_url = "https://dashboard.stripe.com/test/apikeys"
    supports_test_mode = True

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in
                        (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        key = self.config.get("STRIPE_API_KEY", "") or ""
        # Test-mode keys start with sk_test_ ; the Emergent-injected key
        # `sk_test_emergent` also matches.
        return key.startswith("sk_test_")

    async def health_check(self) -> HealthResult:
        # Cheap: verify the SDK class is importable + we have an API key.
        if not self.config.get("STRIPE_API_KEY"):
            return HealthResult(healthy=False, error="STRIPE_API_KEY not set")
        try:
            from emergentintegrations.payments.stripe.checkout import StripeCheckout  # noqa: F401
        except Exception as e:  # noqa: BLE001
            return HealthResult(healthy=False, error=f"sdk_import_failed: {e}")
        return HealthResult(healthy=True)

    async def test_connection(self) -> TestResult:
        """Deeper probe — instantiates the client to prove the API key parses.
        No API call is made (Flow B has no cheap ping); success = SDK
        constructed OK."""
        t0 = time.time()
        try:
            from emergentintegrations.payments.stripe.checkout import StripeCheckout
            StripeCheckout(api_key=self.config["STRIPE_API_KEY"],
                            webhook_url="https://example.invalid/webhook/stripe")
        except Exception as e:  # noqa: BLE001
            self.record_error(ProviderError("stripe_init_failed", str(e)[:160],
                                            provider=self.slug))
            return TestResult(ok=False, detail=str(e)[:200])
        self.record_success()
        return TestResult(ok=True, detail="Stripe SDK initialised.",
                           latency_ms=int((time.time() - t0) * 1000))


registry.register(StripeProvider())
