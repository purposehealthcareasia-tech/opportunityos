"""PayPal provider adapter — Milestone F.

Sandbox + Live share the same code path — env `PAYPAL_ENVIRONMENT` selects
the base URL. Real code paths for `get_access_token()` and
`create_order()`. Hard-fails without credentials.

Webhook verification uses PayPal's server-side `POST
/v1/notifications/verify-webhook-signature` endpoint — this is a network
verification (unlike Stripe / Razorpay's cryptographic HMAC). The
`verify_webhook()` method routes through it and hard-fails on any 4xx OR
`verification_status != "SUCCESS"`.
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
from integrations.payments.signature_verifiers import PaymentSignatureError


log = logging.getLogger("oppos.integrations.paypal")


_ENV_BASE = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live":    "https://api-m.paypal.com",
}


class PayPalProvider(BaseProvider):
    slug = "paypal"
    label = "PayPal"
    category = ProviderCategory.PAYMENTS
    required_env = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET")
    optional_env = ("PAYPAL_WEBHOOK_ID", "PAYPAL_ENVIRONMENT")
    docs_url = "https://developer.paypal.com/dashboard/applications/sandbox"
    supports_test_mode = True

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        # Explicit env var overrides; default to sandbox if key looks sandbox-y.
        env = (self.config.get("PAYPAL_ENVIRONMENT") or "").strip().lower()
        if env == "sandbox":
            return True
        if env == "live":
            return False
        # Fallback: any configured PayPal is treated as test-mode until an
        # operator explicitly sets PAYPAL_ENVIRONMENT=live.
        return bool(self.config.get("PAYPAL_CLIENT_ID"))

    def _base_url(self) -> str:
        env = (self.config.get("PAYPAL_ENVIRONMENT") or "sandbox").strip().lower()
        return _ENV_BASE.get(env, _ENV_BASE["sandbox"])

    def _basic_auth_header(self) -> str:
        raw = f"{self.config['PAYPAL_CLIENT_ID']}:{self.config['PAYPAL_CLIENT_SECRET']}"
        return "Basic " + base64.b64encode(raw.encode()).decode()

    async def _get_access_token(self) -> str:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{self._base_url()}/v1/oauth2/token",
                    data={"grant_type": "client_credentials"},
                    headers={"Authorization": self._basic_auth_header(),
                              "Content-Type": "application/x-www-form-urlencoded"},
                )
            if not r.is_success:
                raise ProviderError("paypal_auth_failed",
                                     f"HTTP {r.status_code}: {r.text[:200]}",
                                     provider=self.slug, http_status=r.status_code)
            return r.json()["access_token"]
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError("paypal_auth_error", str(e)[:200],
                                 provider=self.slug, retryable=True) from e

    async def test_connection(self) -> TestResult:
        validation = self.validate_configuration()
        if not validation.ok:
            return TestResult(ok=False,
                              detail=f"CONFIGURATION_REQUIRED — set: {', '.join(validation.missing_env)}")
        try:
            t0 = time.time()
            _ = await self._get_access_token()
            return TestResult(ok=True, detail="PayPal OAuth OK.",
                               latency_ms=int((time.time() - t0) * 1000))
        except ProviderError as e:
            return TestResult(ok=False, detail=str(e)[:200])

    async def create_order(self, *, amount: str, currency: str = "USD",
                             reference_id: str | None = None) -> dict[str, Any]:
        """Create a PayPal order. `amount` is a decimal-formatted string."""
        validation = self.validate_configuration()
        if not validation.ok:
            raise ProviderError("configuration_required",
                                 f"missing env: {', '.join(validation.missing_env)}",
                                 provider=self.slug)
        token = await self._get_access_token()
        payload: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {"currency_code": currency, "value": str(amount)},
                **({"reference_id": reference_id} if reference_id else {}),
            }],
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{self._base_url()}/v2/checkout/orders",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}",
                              "Content-Type": "application/json"},
                )
            if not r.is_success:
                raise ProviderError("create_order_failed",
                                     f"paypal HTTP {r.status_code}: {r.text[:200]}",
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

    async def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> None:
        """Verify a PayPal webhook via server-to-server round-trip.

        Hard-fails if:
          - `PAYPAL_WEBHOOK_ID` is not configured.
          - Any required signature header is missing.
          - PayPal's `verify-webhook-signature` endpoint returns non-SUCCESS.
        """
        webhook_id = self.config.get("PAYPAL_WEBHOOK_ID") or ""
        if not webhook_id:
            raise PaymentSignatureError("webhook_id_not_configured")
        required = ("paypal-transmission-id", "paypal-transmission-time",
                     "paypal-cert-url", "paypal-auth-algo", "paypal-transmission-sig")
        lower = {k.lower(): v for k, v in headers.items()}
        missing = [h for h in required if not lower.get(h)]
        if missing:
            raise PaymentSignatureError(f"missing_headers:{','.join(missing)}")

        try:
            token = await self._get_access_token()
        except ProviderError as e:
            raise PaymentSignatureError(f"auth_failed:{e}") from e

        # Parse the raw JSON body once (PayPal wants webhook_event as an object).
        import json
        try:
            webhook_event = json.loads(raw_body.decode("utf-8"))
        except Exception as e:
            raise PaymentSignatureError(f"bad_body:{e}") from e

        payload = {
            "auth_algo":         lower["paypal-auth-algo"],
            "cert_url":          lower["paypal-cert-url"],
            "transmission_id":   lower["paypal-transmission-id"],
            "transmission_sig":  lower["paypal-transmission-sig"],
            "transmission_time": lower["paypal-transmission-time"],
            "webhook_id":        webhook_id,
            "webhook_event":     webhook_event,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{self._base_url()}/v1/notifications/verify-webhook-signature",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}",
                              "Content-Type": "application/json"},
                )
        except Exception as e:
            raise PaymentSignatureError(f"upstream_error:{e}") from e
        if not r.is_success:
            raise PaymentSignatureError(f"verify_failed:HTTP {r.status_code}")
        body = r.json()
        if body.get("verification_status") != "SUCCESS":
            raise PaymentSignatureError(f"invalid_signature:{body.get('verification_status')}")


registry.register(PayPalProvider())
