"""Twilio Verify adapter — Milestone D.

`start_verify()` starts an SMS/WhatsApp OTP challenge; `check_verify()`
consumes a code. Both hard-fail without credentials (no bypass mode).

Twilio Verify itself is a synchronous request/response flow — the account
optionally receives status-update webhooks that carry an `X-Twilio-Signature`
header. We implement a signature helper for that here so future webhook
routes can plug in with hard-fail semantics.

Status matrix:
  - CONFIGURATION_REQUIRED: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN /
    TWILIO_VERIFY_SERVICE_SID missing.
  - TEST_MODE: keys present. Twilio trial accounts share the same API surface
    as production so the adapter cannot distinguish them cryptographically.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
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


log = logging.getLogger("oppos.integrations.twilio")


class TwilioSignatureError(Exception):
    """Raised when a Twilio webhook fails signature verification."""


class TwilioVerifyProvider(BaseProvider):
    slug = "twilio"
    label = "Twilio Verify (OTP)"
    category = ProviderCategory.SMS
    required_env = (
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_VERIFY_SERVICE_SID",
    )
    optional_env = ("TWILIO_STATUS_CALLBACK_URL",)
    docs_url = "https://www.twilio.com/docs/verify/api"
    supports_test_mode = True

    _api_base = "https://verify.twilio.com/v2"

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        return bool(self.config.get("TWILIO_ACCOUNT_SID"))

    def _auth(self) -> tuple[str, str]:
        return (self.config["TWILIO_ACCOUNT_SID"], self.config["TWILIO_AUTH_TOKEN"])

    async def test_connection(self) -> TestResult:
        validation = self.validate_configuration()
        if not validation.ok:
            return TestResult(ok=False,
                              detail=f"CONFIGURATION_REQUIRED — set: {', '.join(validation.missing_env)}")
        sid = self.config["TWILIO_VERIFY_SERVICE_SID"]
        try:
            t0 = time.time()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self._api_base}/Services/{sid}", auth=self._auth())
            latency_ms = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                return TestResult(ok=True, detail="Twilio Verify /Services/{sid} OK.",
                                   latency_ms=latency_ms)
            return TestResult(ok=False, detail=f"Twilio HTTP {r.status_code}.",
                               latency_ms=latency_ms)
        except Exception as e:
            return TestResult(ok=False, detail=f"probe_error: {str(e)[:200]}")

    # ---- OTP flow --------------------------------------------------------

    async def start_verify(self, *, to: str, channel: str = "sms") -> dict[str, Any]:
        validation = self.validate_configuration()
        if not validation.ok:
            raise ProviderError("configuration_required",
                                 f"missing env: {', '.join(validation.missing_env)}",
                                 provider=self.slug)
        sid = self.config["TWILIO_VERIFY_SERVICE_SID"]
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{self._api_base}/Services/{sid}/Verifications",
                    data={"To": to, "Channel": channel},
                    auth=self._auth(),
                )
            if not r.is_success:
                raise ProviderError("start_verify_failed",
                                     f"twilio HTTP {r.status_code}: {r.text[:200]}",
                                     provider=self.slug, http_status=r.status_code,
                                     retryable=r.status_code >= 500)
            body = r.json()
            self.record_success()
            return {"sid": body.get("sid"), "status": body.get("status"),
                    "to": body.get("to"), "channel": body.get("channel")}
        except ProviderError:
            raise
        except Exception as e:
            err = ProviderError("start_verify_error", str(e)[:200],
                                 provider=self.slug, retryable=True)
            self.record_error(err)
            raise err

    async def check_verify(self, *, to: str, code: str) -> dict[str, Any]:
        validation = self.validate_configuration()
        if not validation.ok:
            raise ProviderError("configuration_required",
                                 f"missing env: {', '.join(validation.missing_env)}",
                                 provider=self.slug)
        sid = self.config["TWILIO_VERIFY_SERVICE_SID"]
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{self._api_base}/Services/{sid}/VerificationCheck",
                    data={"To": to, "Code": code},
                    auth=self._auth(),
                )
            if not r.is_success:
                raise ProviderError("check_verify_failed",
                                     f"twilio HTTP {r.status_code}: {r.text[:200]}",
                                     provider=self.slug, http_status=r.status_code,
                                     retryable=r.status_code >= 500)
            body = r.json()
            approved = body.get("status") == "approved"
            if approved:
                self.record_success()
            return {"approved": approved, "status": body.get("status"),
                    "sid": body.get("sid")}
        except ProviderError:
            raise
        except Exception as e:
            err = ProviderError("check_verify_error", str(e)[:200],
                                 provider=self.slug, retryable=True)
            self.record_error(err)
            raise err

    # ---- webhook signature ----------------------------------------------

    def verify_webhook_signature(self, *, url: str, form_params: dict[str, str],
                                    header_signature: str) -> None:
        """Verify Twilio's `X-Twilio-Signature` header.

        Canonical string: full URL + concatenated (sorted-by-key) form-param
        `key+value` pairs. HMAC-SHA1 keyed with `TWILIO_AUTH_TOKEN`. Result
        is base64-encoded and MUST match the header. Hard-fails when the
        token is not configured or the signature is wrong.
        """
        token = self.config.get("TWILIO_AUTH_TOKEN") or ""
        if not token:
            raise TwilioSignatureError("auth_token_not_configured")
        if not header_signature:
            raise TwilioSignatureError("missing_signature_header")
        canonical = url
        for k in sorted(form_params.keys()):
            canonical += f"{k}{form_params[k]}"
        digest = hmac.new(token.encode("utf-8"), canonical.encode("utf-8"),
                            hashlib.sha1).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        if not hmac.compare_digest(expected, header_signature):
            raise TwilioSignatureError("invalid_signature")


registry.register(TwilioVerifyProvider())
