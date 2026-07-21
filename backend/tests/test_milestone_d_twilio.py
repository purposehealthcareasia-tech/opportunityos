"""Milestone D — Twilio Verify (OTP) adapter regression.

Coverage:
  1. Provider status matrix — CONFIGURATION_REQUIRED without credentials.
  2. `start_verify()` / `check_verify()` hard-fail without credentials.
  3. `verify_webhook_signature()` hard-fails on missing token, wrong header,
     wrong signature; passes on a valid signature computed with a
     locally-supplied token.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

import pytest


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_registry():
    from integrations import registry
    registry.load_all()
    yield


@pytest.fixture(scope="module")
def twilio_provider():
    from integrations import registry
    return registry.get("twilio")


class TestProviderStatus:
    def test_configuration_required_without_creds(self, twilio_provider):
        assert not os.environ.get("TWILIO_ACCOUNT_SID"), \
            "Preview should not have TWILIO_ACCOUNT_SID set for this test."
        d = twilio_provider.describe()
        assert d["status"] == "CONFIGURATION_REQUIRED"
        assert set(d["missing_env"]) == {
            "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID",
        }


class TestOtpFlowHardFail:
    @pytest.mark.asyncio
    async def test_start_verify_hardfails_without_creds(self, twilio_provider):
        from integrations.base import ProviderError
        with pytest.raises(ProviderError) as ei:
            await twilio_provider.start_verify(to="+15551234567", channel="sms")
        assert ei.value.code == "configuration_required"

    @pytest.mark.asyncio
    async def test_check_verify_hardfails_without_creds(self, twilio_provider):
        from integrations.base import ProviderError
        with pytest.raises(ProviderError) as ei:
            await twilio_provider.check_verify(to="+15551234567", code="123456")
        assert ei.value.code == "configuration_required"


class TestTwilioSignatureVerification:
    def _apply_token(self, provider, token: str) -> None:
        provider.config["TWILIO_AUTH_TOKEN"] = token

    def test_missing_token_hardfails(self, twilio_provider):
        from integrations.sms.twilio_provider import TwilioSignatureError
        # Reset config to unconfigured state.
        twilio_provider.configure()
        assert not twilio_provider.config.get("TWILIO_AUTH_TOKEN")
        with pytest.raises(TwilioSignatureError) as ei:
            twilio_provider.verify_webhook_signature(
                url="https://example.com/hook", form_params={"a": "1"},
                header_signature="anything",
            )
        assert "auth_token_not_configured" in str(ei.value)

    def test_missing_header_hardfails(self, twilio_provider):
        from integrations.sms.twilio_provider import TwilioSignatureError
        self._apply_token(twilio_provider, "test-token")
        try:
            with pytest.raises(TwilioSignatureError) as ei:
                twilio_provider.verify_webhook_signature(
                    url="https://example.com/hook",
                    form_params={}, header_signature="",
                )
            assert "missing_signature_header" in str(ei.value)
        finally:
            twilio_provider.configure()

    def test_valid_signature_accepted(self, twilio_provider):
        token = "my-test-token"
        self._apply_token(twilio_provider, token)
        try:
            url = "https://example.com/twilio/hook"
            form = {"MessageSid": "SM123", "To": "+15551234567", "From": "+15559999999"}
            canonical = url + "".join(f"{k}{form[k]}" for k in sorted(form))
            digest = hmac.new(token.encode(), canonical.encode(), hashlib.sha1).digest()
            expected = base64.b64encode(digest).decode()
            # Should NOT raise.
            twilio_provider.verify_webhook_signature(
                url=url, form_params=form, header_signature=expected,
            )
        finally:
            twilio_provider.configure()

    def test_bad_signature_rejected(self, twilio_provider):
        from integrations.sms.twilio_provider import TwilioSignatureError
        self._apply_token(twilio_provider, "my-test-token")
        try:
            with pytest.raises(TwilioSignatureError) as ei:
                twilio_provider.verify_webhook_signature(
                    url="https://example.com/twilio/hook",
                    form_params={"MessageSid": "SM1"},
                    header_signature="wrong-signature",
                )
            assert "invalid_signature" in str(ei.value)
        finally:
            twilio_provider.configure()
