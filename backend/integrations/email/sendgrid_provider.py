"""SendGrid transactional email adapter — Milestone C.

Send path uses httpx against `https://api.sendgrid.com/v3/mail/send`.
Webhook path uses `verify_sendgrid_signature` (ECDSA P-256 over
`timestamp + raw_body`). Both hard-fail without secrets — no bypass mode.

Status matrix:
  - CONFIGURATION_REQUIRED: SENDGRID_API_KEY or SENDGRID_FROM_EMAIL missing.
  - TEST_MODE: keys present. SendGrid uses the same live API for
    sandbox-mode sends; report TEST_MODE until domain is fully validated.
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
    verify_sendgrid_signature, VerifiedWebhook, WebhookVerificationError,
)


log = logging.getLogger("oppos.integrations.sendgrid")


class SendGridEmailProvider(BaseProvider):
    slug = "sendgrid"
    label = "SendGrid"
    category = ProviderCategory.EMAIL
    required_env = ("SENDGRID_API_KEY", "SENDGRID_FROM_EMAIL")
    optional_env = ("SENDGRID_WEBHOOK_VERIFICATION_KEY",)
    docs_url = "https://app.sendgrid.com/settings/api_keys"
    supports_test_mode = True

    _mail_url = "https://api.sendgrid.com/v3/mail/send"
    _profile_url = "https://api.sendgrid.com/v3/user/profile"

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        return bool(self.config.get("SENDGRID_API_KEY"))

    async def test_connection(self) -> TestResult:
        validation = self.validate_configuration()
        if not validation.ok:
            return TestResult(ok=False,
                              detail=f"CONFIGURATION_REQUIRED — set: {', '.join(validation.missing_env)}")
        key = self.config.get("SENDGRID_API_KEY", "")
        try:
            t0 = time.time()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(self._profile_url,
                                       headers={"Authorization": f"Bearer {key}"})
            latency_ms = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                return TestResult(ok=True, detail="SendGrid /user/profile OK.",
                                   latency_ms=latency_ms)
            return TestResult(ok=False, detail=f"SendGrid HTTP {r.status_code}.",
                               latency_ms=latency_ms)
        except Exception as e:
            return TestResult(ok=False, detail=f"probe_error: {str(e)[:200]}")

    # ---- send ------------------------------------------------------------

    async def send(self, *, to: str, subject: str, html: str,
                    text: Optional[str] = None,
                    metadata: Optional[dict[str, str]] = None) -> dict[str, Any]:
        validation = self.validate_configuration()
        if not validation.ok:
            raise ProviderError("configuration_required",
                                 f"missing env: {', '.join(validation.missing_env)}",
                                 provider=self.slug)
        content = [{"type": "text/html", "value": html}]
        if text:
            content.append({"type": "text/plain", "value": text})
        personalization: dict[str, Any] = {"to": [{"email": to}]}
        if metadata:
            personalization["custom_args"] = {k: str(v) for k, v in metadata.items()}
        payload = {
            "personalizations": [personalization],
            "from": {"email": self.config["SENDGRID_FROM_EMAIL"]},
            "subject": subject,
            "content": content,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    self._mail_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {self.config['SENDGRID_API_KEY']}",
                              "Content-Type": "application/json"},
                )
            if not r.is_success:
                raise ProviderError("send_failed", f"sendgrid HTTP {r.status_code}: {r.text[:200]}",
                                     provider=self.slug, http_status=r.status_code,
                                     retryable=r.status_code >= 500)
            self.record_success()
            # SendGrid's mail/send returns 202 + empty body; expose the message id header if present.
            return {"status_code": r.status_code,
                    "x_message_id": r.headers.get("X-Message-Id")}
        except ProviderError:
            raise
        except Exception as e:
            err = ProviderError("send_error", str(e)[:200], provider=self.slug, retryable=True)
            self.record_error(err)
            raise err

    # ---- webhook verification -------------------------------------------

    def verify_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> VerifiedWebhook:
        public_pem = self.config.get("SENDGRID_WEBHOOK_VERIFICATION_KEY") or ""
        return verify_sendgrid_signature(
            raw_body=raw_body, headers=headers, public_key_pem=public_pem,
        )


registry.register(SendGridEmailProvider())
