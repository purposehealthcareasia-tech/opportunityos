"""Paystack provider adapter — Milestone A stub.

Adapter registered so the admin Integrations dashboard shows honest
CONFIGURATION_REQUIRED status until real credentials + full flow arrive
in the milestone that owns this category. Deep implementation:
Milestone C (Stripe) / D (Razorpay+PayPal+Paystack)."""
from __future__ import annotations

import os
from integrations.base import (
    BaseProvider, ProviderCategory, HealthResult, TestResult,
)
from integrations import registry


class PaystackProvider(BaseProvider):
    slug = "paystack"
    label = "Paystack"
    category = ProviderCategory.PAYMENTS
    required_env = ('PAYSTACK_SECRET_KEY',)
    optional_env = ('PAYSTACK_PUBLIC_KEY', 'PAYSTACK_WEBHOOK_SECRET')
    docs_url = "https://dashboard.paystack.com/#/settings/developers"
    supports_test_mode = True

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


registry.register(PaystackProvider())
