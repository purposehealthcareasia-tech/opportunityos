"""Resend transactional email adapter — Milestone C.

Send path uses httpx against `https://api.resend.com/emails` (playbook §Resend).
Webhook path uses `verify_svix_signature` (HMAC-SHA256 over `id.ts.body`).
Both hard-fail without the corresponding secrets — no bypass mode.

Status matrix:
  - CONFIGURATION_REQUIRED: RESEND_API_KEY or RESEND_FROM_EMAIL missing.
  - TEST_MODE: keys present. Resend has no distinct sandbox — treat as
    TEST_MODE until the operator activates a production domain.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx

from integrations.base import (
    BaseProvider, ProviderCategory, HealthResult, TestResult, ConfigValidation,
    ProviderError,
)
from integrations import registry
from integrations.email.webhook_verifiers import (
    verify_svix_signature, VerifiedWebhook, WebhookVerificationError,
)


log = logging.getLogger("oppos.integrations.resend")


class ResendEmailProvider(BaseProvider):
    slug = "resend"
    label = "Resend"
    category = ProviderCategory.EMAIL
    required_env = ("RESEND_API_KEY", "RESEND_FROM_EMAIL")
    optional_env = ("RESEND_WEBHOOK_SECRET",)
    docs_url = "https://resend.com/api-keys"
    supports_test_mode = True

    _api_url = "https://api.resend.com/emails"

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        # Resend has no distinct sandbox key namespace — treat any working key
        # as test-mode until the operator flips a domain to production.
        return bool(self.config.get("RESEND_API_KEY"))

    async def test_connection(self) -> TestResult:
        validation = self.validate_configuration()
        if not validation.ok:
            return TestResult(ok=False,
                              detail=f"CONFIGURATION_REQUIRED — set: {', '.join(validation.missing_env)}")
        # Do NOT actually send an email — just verify the API key by hitting
        # the `/domains` endpoint, which requires auth but has no send cost.
        key = self.config.get("RESEND_API_KEY", "")
        try:
            t0 = time.time()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get("https://api.resend.com/domains",
                                       headers={"Authorization": f"Bearer {key}"})
            latency_ms = int((time.time() - t0) * 1000)
            if r.status_code in (200, 401, 403):
                if r.status_code == 200:
                    return TestResult(ok=True, detail="Resend /domains OK.",
                                       latency_ms=latency_ms)
                return TestResult(ok=False,
                                   detail=f"Resend rejected key ({r.status_code}).",
                                   latency_ms=latency_ms)
            return TestResult(ok=False, detail=f"Resend HTTP {r.status_code}.",
                               latency_ms=latency_ms)
        except Exception as e:
            return TestResult(ok=False, detail=f"probe_error: {str(e)[:200]}")

    # ---- send ------------------------------------------------------------

    async def send(self, *, to: str, subject: str, html: str,
                    text: Optional[str] = None,
                    metadata: Optional[dict[str, str]] = None) -> dict[str, Any]:
        """Send a transactional email. Hard-fails on CONFIGURATION_REQUIRED."""
        validation = self.validate_configuration()
        if not validation.ok:
            raise ProviderError("configuration_required",
                                 f"missing env: {', '.join(validation.missing_env)}",
                                 provider=self.slug)
        payload: dict[str, Any] = {
            "from": self.config["RESEND_FROM_EMAIL"],
            "to": [to],
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text
        if metadata:
            payload["headers"] = {f"X-Meta-{k}": str(v) for k, v in metadata.items()}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    self._api_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.config['RESEND_API_KEY']}"},
                )
            if not r.is_success:
                raise ProviderError("send_failed", f"resend HTTP {r.status_code}: {r.text[:200]}",
                                     provider=self.slug, http_status=r.status_code,
                                     retryable=r.status_code >= 500)
            self.record_success()
            return r.json()
        except ProviderError:
            raise
        except Exception as e:
            err = ProviderError("send_error", str(e)[:200], provider=self.slug, retryable=True)
            self.record_error(err)
            raise err

    # ---- webhook verification -------------------------------------------

    def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> VerifiedWebhook:
        """Verify an incoming webhook. Raises WebhookVerificationError on
        missing secret (hard-fail) or invalid signature."""
        secret = self.config.get("RESEND_WEBHOOK_SECRET") or ""
        return verify_svix_signature(
            raw_body=raw_body, headers=headers, webhook_secret=secret,
        )


registry.register(ResendEmailProvider())
