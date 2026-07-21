"""Razorpay provider adapter — Milestone F.

Real code paths for `create_order()` and `verify_webhook()`. Hard-fails
without credentials. Uses Basic Auth over httpx (no SDK dependency).
"""
from __future__ import annotations

import base64
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
    verify_razorpay_signature, PaymentSignatureError,
)


log = logging.getLogger("oppos.integrations.razorpay")


class RazorpayProvider(BaseProvider):
    slug = "razorpay"
    label = "Razorpay"
    category = ProviderCategory.PAYMENTS
    required_env = ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET")
    optional_env = ("RAZORPAY_WEBHOOK_SECRET",)
    docs_url = "https://dashboard.razorpay.com/app/keys"
    supports_test_mode = True

    _api_base = "https://api.razorpay.com/v1"

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        # Razorpay test key ids start with `rzp_test_`.
        return (self.config.get("RAZORPAY_KEY_ID") or "").startswith("rzp_test_")

    def _auth(self) -> tuple[str, str]:
        return (self.config["RAZORPAY_KEY_ID"], self.config["RAZORPAY_KEY_SECRET"])

    async def test_connection(self) -> TestResult:
        validation = self.validate_configuration()
        if not validation.ok:
            return TestResult(ok=False,
                              detail=f"CONFIGURATION_REQUIRED — set: {', '.join(validation.missing_env)}")
        try:
            t0 = time.time()
            async with httpx.AsyncClient(timeout=10.0) as client:
                # /payments?count=1 is auth-only, no cost.
                r = await client.get(f"{self._api_base}/payments?count=1", auth=self._auth())
            latency_ms = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                return TestResult(ok=True, detail="Razorpay auth OK.",
                                   latency_ms=latency_ms)
            return TestResult(ok=False, detail=f"Razorpay HTTP {r.status_code}.",
                               latency_ms=latency_ms)
        except Exception as e:
            return TestResult(ok=False, detail=f"probe_error: {str(e)[:200]}")

    async def create_order(self, *, amount_paise: int, currency: str = "INR",
                             receipt: str | None = None,
                             notes: dict[str, str] | None = None) -> dict[str, Any]:
        validation = self.validate_configuration()
        if not validation.ok:
            raise ProviderError("configuration_required",
                                 f"missing env: {', '.join(validation.missing_env)}",
                                 provider=self.slug)
        payload: dict[str, Any] = {"amount": amount_paise, "currency": currency}
        if receipt:
            payload["receipt"] = receipt
        if notes:
            payload["notes"] = {k: str(v) for k, v in notes.items()}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(f"{self._api_base}/orders", json=payload, auth=self._auth())
            if not r.is_success:
                raise ProviderError("create_order_failed",
                                     f"razorpay HTTP {r.status_code}: {r.text[:200]}",
                                     provider=self.slug, http_status=r.status_code,
                                     retryable=r.status_code >= 500)
            self.record_success()
            return r.json()
        except ProviderError:
            raise
        except Exception as e:
            err = ProviderError("create_order_error", str(e)[:200],
                                 provider=self.slug, retryable=True)
            self.record_error(err)
            raise err

    def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> None:
        secret = self.config.get("RAZORPAY_WEBHOOK_SECRET") or ""
        header = headers.get("X-Razorpay-Signature") or headers.get("x-razorpay-signature") or ""
        verify_razorpay_signature(raw_body=raw_body, header=header, webhook_secret=secret)


registry.register(RazorpayProvider())
