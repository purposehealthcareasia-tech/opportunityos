"""Stripe provider adapter — Milestone F.

Milestone A: registration + truthful status + `test_connection()`.
Milestone F additions:
    - `verify_webhook()` — cryptographic HMAC-SHA256 signature check that
      matches Stripe's algorithm exactly (delegates to
      `integrations.payments.signature_verifiers.verify_stripe_signature`).
      Runs independently of the `emergentintegrations` SDK so the unified
      layer can eventually drop the SDK dependency for webhook handling.
    - `create_checkout_session()` thin wrapper matching the legacy
      `domains/billing/service.py` shape — the billing route may be
      migrated to this adapter in a follow-up (strangler pattern).

Existing S19 acceptance tests continue to run against the legacy billing
service; nothing here modifies that path.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from integrations.base import (
    BaseProvider, ProviderCategory, ConfigValidation, HealthResult, TestResult,
    ProviderError,
)
from integrations import registry
from integrations.payments.signature_verifiers import (
    verify_stripe_signature, PaymentSignatureError,
)


log = logging.getLogger("oppos.integrations.stripe")


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
        return key.startswith("sk_test_")

    async def health_check(self) -> HealthResult:
        if not self.config.get("STRIPE_API_KEY"):
            return HealthResult(healthy=False, error="STRIPE_API_KEY not set")
        try:
            from emergentintegrations.payments.stripe.checkout import StripeCheckout  # noqa: F401
        except Exception as e:
            return HealthResult(healthy=False, error=f"sdk_import_failed: {e}")
        return HealthResult(healthy=True)

    async def test_connection(self) -> TestResult:
        t0 = time.time()
        try:
            from emergentintegrations.payments.stripe.checkout import StripeCheckout
            StripeCheckout(api_key=self.config["STRIPE_API_KEY"],
                            webhook_url="https://example.invalid/webhook/stripe")
        except Exception as e:
            self.record_error(ProviderError("stripe_init_failed", str(e)[:160],
                                            provider=self.slug))
            return TestResult(ok=False, detail=str(e)[:200])
        self.record_success()
        return TestResult(ok=True, detail="Stripe SDK initialised.",
                           latency_ms=int((time.time() - t0) * 1000))

    # ---- Milestone F additions ------------------------------------------

    async def create_checkout_session(self, *, amount: float, currency: str,
                                          success_url: str, cancel_url: str,
                                          webhook_url: str | None = None,
                                          metadata: dict[str, str] | None = None) -> dict[str, Any]:
        """Thin wrapper over `emergentintegrations.payments.stripe.checkout`.

        Hard-fails on `configuration_required`. Returns
        `{session_id, url, amount}` matching the legacy billing shape.
        """
        validation = self.validate_configuration()
        if not validation.ok:
            raise ProviderError("configuration_required",
                                 f"missing env: {', '.join(validation.missing_env)}",
                                 provider=self.slug)
        try:
            from emergentintegrations.payments.stripe.checkout import (
                StripeCheckout, CheckoutSessionRequest,
            )
            client = StripeCheckout(api_key=self.config["STRIPE_API_KEY"],
                                     webhook_url=webhook_url or "https://example.invalid/webhook/stripe")
            req = CheckoutSessionRequest(
                amount=amount, currency=currency,
                success_url=success_url, cancel_url=cancel_url,
                metadata=metadata or {},
            )
            session = await client.create_checkout_session(req)
            self.record_success()
            return {"session_id": session.session_id, "url": session.url,
                    "amount": amount}
        except ProviderError:
            raise
        except Exception as e:
            err = ProviderError("create_checkout_failed", str(e)[:200],
                                 provider=self.slug, retryable=True)
            self.record_error(err)
            raise err

    def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> None:
        """Cryptographic verification of Stripe's `Stripe-Signature` header.

        Hard-fails when `STRIPE_WEBHOOK_SECRET` is unset — legacy billing
        code still uses the emergent SDK's verifier; this adapter's method
        exists so a future strangler migration can retire that dependency.
        """
        secret = self.config.get("STRIPE_WEBHOOK_SECRET") or ""
        header = headers.get("Stripe-Signature") or headers.get("stripe-signature") or ""
        verify_stripe_signature(raw_body=raw_body, header=header,
                                  webhook_secret=secret)


registry.register(StripeProvider())
