"""Paystack provider adapter — Milestone F.

Real code paths for `initialize_transaction()` and `verify_webhook()`.
Hard-fails without credentials. Uses Bearer auth over httpx.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from integrations.base import (
    BaseProvider, ProviderCategory, HealthResult, TestResult, ConfigValidation,
    ProviderError,
)
from integrations import registry
from integrations.payments.signature_verifiers import (
    verify_paystack_signature, PaymentSignatureError,
)


log = logging.getLogger("oppos.integrations.paystack")


class PaystackProvider(BaseProvider):
    slug = "paystack"
    label = "Paystack"
    category = ProviderCategory.PAYMENTS
    required_env = ("PAYSTACK_SECRET_KEY",)
    optional_env = ("PAYSTACK_PUBLIC_KEY", "PAYSTACK_WEBHOOK_SECRET")
    docs_url = "https://dashboard.paystack.com/#/settings/developers"
    supports_test_mode = True

    _api_base = "https://api.paystack.co"

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        return (self.config.get("PAYSTACK_SECRET_KEY") or "").startswith("sk_test_")

    def _bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config['PAYSTACK_SECRET_KEY']}"}

    async def test_connection(self) -> TestResult:
        validation = self.validate_configuration()
        if not validation.ok:
            return TestResult(ok=False,
                              detail=f"CONFIGURATION_REQUIRED — set: {', '.join(validation.missing_env)}")
        try:
            t0 = time.time()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self._api_base}/balance", headers=self._bearer())
            latency_ms = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                return TestResult(ok=True, detail="Paystack /balance OK.",
                                   latency_ms=latency_ms)
            return TestResult(ok=False, detail=f"Paystack HTTP {r.status_code}.",
                               latency_ms=latency_ms)
        except Exception as e:
            return TestResult(ok=False, detail=f"probe_error: {str(e)[:200]}")

    async def initialize_transaction(self, *, email: str, amount_kobo: int,
                                        currency: str = "NGN",
                                        reference: str | None = None,
                                        callback_url: str | None = None) -> dict[str, Any]:
        validation = self.validate_configuration()
        if not validation.ok:
            raise ProviderError("configuration_required",
                                 f"missing env: {', '.join(validation.missing_env)}",
                                 provider=self.slug)
        payload: dict[str, Any] = {"email": email, "amount": amount_kobo,
                                     "currency": currency}
        if reference:
            payload["reference"] = reference
        if callback_url:
            payload["callback_url"] = callback_url
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(f"{self._api_base}/transaction/initialize",
                                        json=payload, headers=self._bearer())
            if not r.is_success:
                raise ProviderError("initialize_failed",
                                     f"paystack HTTP {r.status_code}: {r.text[:200]}",
                                     provider=self.slug, http_status=r.status_code,
                                     retryable=r.status_code >= 500)
            self.record_success()
            return r.json()
        except ProviderError:
            raise
        except Exception as e:
            err = ProviderError("initialize_error", str(e)[:200],
                                 provider=self.slug, retryable=True)
            self.record_error(err)
            raise err

    def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> None:
        # Paystack signs with the SECRET_KEY, not a dedicated webhook secret.
        # Operator may still override via PAYSTACK_WEBHOOK_SECRET.
        secret = (self.config.get("PAYSTACK_WEBHOOK_SECRET")
                  or self.config.get("PAYSTACK_SECRET_KEY") or "")
        header = headers.get("x-paystack-signature") or headers.get("X-Paystack-Signature") or ""
        verify_paystack_signature(raw_body=raw_body, header=header, webhook_secret=secret)


registry.register(PaystackProvider())
