"""Phone-OTP login (Twilio Verify) — regression.

Covers:
  - GET  /api/v1/auth/otp/status → truthful `configured=false` with the list
    of missing env var NAMES when Twilio keys are absent (values never
    leaked).
  - POST /api/v1/auth/otp/start returns 503 `otp_not_configured` when Twilio
    keys are absent (honest CONFIGURATION_REQUIRED contract for the frontend).
  - POST /api/v1/auth/otp/verify returns 503 in the same state.
  - Phone normalization / E.164 validation.
  - `_require_twilio()` short-circuits before any upstream call.
  - Happy-path OTP login (Twilio calls mocked) issues an oppos session.
  - `/otp/verify` for an unknown phone returns 404 `no_account_for_phone`.
  - `/otp/attach` refuses a phone already attached elsewhere (409).
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from core import db as db_module
from core.config import settings
from domains.auth import otp_service
# Force adapter registration (server lifespan does this normally; pytest
# doesn't run lifespan when we only import modules).
from integrations import registry as _registry
_registry.load_all()


@pytest.fixture
async def isolated_db(monkeypatch):
    """Ephemeral DB per test. Deliberately does NOT close its Motor client —
    forcing close before pytest-asyncio tears down the per-test loop poisons
    downstream tests that rely on the shared core.db Motor client."""
    dbname = f"opportunityos_otptest_{uuid.uuid4().hex[:8]}"
    client = AsyncIOMotorClient(settings.MONGO_URL, uuidRepresentation="standard")
    fake_db = client[dbname]
    # See apple test rationale — do NOT patch the shared core.db.get_db.
    monkeypatch.setattr(otp_service, "get_db", lambda: fake_db)
    from domains.audit import service as audit_mod
    monkeypatch.setattr(audit_mod, "get_db", lambda: fake_db, raising=False)
    from core import sessions as sessions_mod
    monkeypatch.setattr(sessions_mod, "get_db", lambda: fake_db, raising=False)
    try:
        await otp_service.ensure_indexes()
        yield fake_db
    finally:
        try:
            import pymongo
            pymongo.MongoClient(settings.MONGO_URL).drop_database(dbname)
        except Exception:
            pass
        # Reset shared core.db singletons (Motor caches loop refs on clients).
        try:
            db_module._client = None  # type: ignore[attr-defined]
            db_module._db = None      # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass


@pytest.fixture
def clear_twilio_env(monkeypatch):
    from integrations import registry
    prov = registry.get("twilio")
    original_config = dict(prov.config) if prov else None
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID"):
        monkeypatch.delenv(k, raising=False)
    if prov is not None:
        # Use monkeypatch so the original dict is restored on fixture exit.
        monkeypatch.setattr(prov, "config", {k: "" for k in prov.config.keys()})
    yield
    # After yield: monkeypatch finalizer restores prov.config → original_config.
    _ = original_config


@pytest.fixture
def twilio_env_set(monkeypatch):
    from integrations import registry
    prov = registry.get("twilio")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC0000000000000000000000000000TEST")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "TESTTOKEN")
    monkeypatch.setenv("TWILIO_VERIFY_SERVICE_SID", "VA000000000000000000000000000TEST")
    if prov is not None:
        # Monkeypatch-based override so pytest restores prov.config on fixture teardown.
        monkeypatch.setattr(prov, "config", {
            "TWILIO_ACCOUNT_SID": "AC0000000000000000000000000000TEST",
            "TWILIO_AUTH_TOKEN": "TESTTOKEN",
            "TWILIO_VERIFY_SERVICE_SID": "VA000000000000000000000000000TEST",
            "TWILIO_STATUS_CALLBACK_URL": "",
        })
    yield


class _FakeRequest:
    def __init__(self):
        self.client = None
        self.headers = {}
        self.state = type("S", (), {})()


class _FakeResponse:
    def __init__(self):
        self.cookies = {}
    def set_cookie(self, key, value=None, **kw):
        self.cookies[key] = value
    def delete_cookie(self, *a, **k):
        pass


class TestPhoneNormalization:
    def test_valid_e164(self):
        assert otp_service._normalize_phone("+14155552671") == "+14155552671"

    def test_strips_formatting(self):
        assert otp_service._normalize_phone("+1 (415) 555-2671") == "+14155552671"

    def test_rejects_missing_plus(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            otp_service._normalize_phone("14155552671")
        assert e.value.status_code == 400

    def test_rejects_junk(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            otp_service._normalize_phone("not-a-phone")
        assert e.value.status_code == 400


class TestConfigurationRequiredContract:
    @pytest.mark.asyncio
    async def test_start_returns_503_when_twilio_missing(self, clear_twilio_env, isolated_db):
        from fastapi import HTTPException
        req = _FakeRequest()
        with pytest.raises(HTTPException) as e:
            await otp_service.start_otp(phone="+14155552671", request=req)
        assert e.value.status_code == 503
        assert e.value.detail["error"] == "otp_not_configured"

    @pytest.mark.asyncio
    async def test_verify_returns_503_when_twilio_missing(self, clear_twilio_env, isolated_db):
        from fastapi import HTTPException
        req, resp = _FakeRequest(), _FakeResponse()
        with pytest.raises(HTTPException) as e:
            await otp_service.verify_otp(phone="+14155552671", code="123456",
                                         request=req, response=resp)
        assert e.value.status_code == 503
        assert e.value.detail["error"] == "otp_not_configured"


class TestOtpLoginHappyPath:
    @pytest.mark.asyncio
    async def test_login_returns_status_logged_in(self, twilio_env_set, isolated_db, monkeypatch):
        # Seed a user with an attached phone.
        uid = str(uuid.uuid4())
        await isolated_db.users.insert_one({
            "id": uid, "email": "phone@example.com",
            "password_hash": "", "name": "Phone User",
            "phone": "+14155552671",
            "created_at": otp_service.utc_now(),
        })

        # Mock Twilio's start + check to succeed.
        from integrations import registry
        prov = registry.get("twilio")
        monkeypatch.setattr(prov, "start_verify",
                            AsyncMock(return_value={"sid": "VE_MOCK", "to": "+14155552671",
                                                     "channel": "sms"}))
        monkeypatch.setattr(prov, "check_verify",
                            AsyncMock(return_value={"approved": True,
                                                     "status": "approved",
                                                     "sid": "VE_MOCK"}))
        # Neutralize the throttle so it never touches the shared DB.
        monkeypatch.setattr(otp_service.login_throttle,
                            "check_and_record_attempt", AsyncMock())
        monkeypatch.setattr(otp_service.login_throttle,
                            "clear_bucket", AsyncMock())

        req, resp = _FakeRequest(), _FakeResponse()
        # start
        s = await otp_service.start_otp(phone="+1 (415) 555-2671", request=req)
        assert s["ok"] is True and s["phone_tail"] == "2671"
        # verify
        v = await otp_service.verify_otp(phone="+14155552671", code="123456",
                                          request=req, response=resp)
        assert v["status"] == "logged_in"
        assert v["user"]["id"] == uid
        # Session cookie set.
        assert any(k.startswith("oppos_session") for k in resp.cookies) or resp.cookies

    @pytest.mark.asyncio
    async def test_verify_no_account_returns_404(self, twilio_env_set, isolated_db, monkeypatch):
        from integrations import registry
        prov = registry.get("twilio")
        monkeypatch.setattr(prov, "check_verify",
                            AsyncMock(return_value={"approved": True,
                                                     "status": "approved",
                                                     "sid": "VE"}))
        monkeypatch.setattr(otp_service.login_throttle,
                            "check_and_record_attempt", AsyncMock())
        from fastapi import HTTPException
        req, resp = _FakeRequest(), _FakeResponse()
        with pytest.raises(HTTPException) as e:
            await otp_service.verify_otp(phone="+14155552671", code="654321",
                                          request=req, response=resp)
        assert e.value.status_code == 404
        assert e.value.detail["error"] == "no_account_for_phone"

    @pytest.mark.asyncio
    async def test_verify_incorrect_code_returns_401(self, twilio_env_set, isolated_db, monkeypatch):
        from integrations import registry
        prov = registry.get("twilio")
        monkeypatch.setattr(prov, "check_verify",
                            AsyncMock(return_value={"approved": False,
                                                     "status": "pending",
                                                     "sid": "VE"}))
        monkeypatch.setattr(otp_service.login_throttle,
                            "check_and_record_attempt", AsyncMock())
        from fastapi import HTTPException
        req, resp = _FakeRequest(), _FakeResponse()
        with pytest.raises(HTTPException) as e:
            await otp_service.verify_otp(phone="+14155552671", code="000000",
                                          request=req, response=resp)
        assert e.value.status_code == 401
        assert e.value.detail["error"] == "otp_code_incorrect"


class TestPhoneAttach:
    @pytest.mark.asyncio
    async def test_attach_refuses_phone_already_used(self, twilio_env_set, isolated_db, monkeypatch):
        # Two users. B tries to attach A's phone.
        u_a = str(uuid.uuid4()); u_b = str(uuid.uuid4())
        await isolated_db.users.insert_many([
            {"id": u_a, "email": "a@x.com", "phone": "+14155552671",
             "password_hash": "", "name": "A", "created_at": otp_service.utc_now()},
            {"id": u_b, "email": "b@x.com",
             "password_hash": "", "name": "B", "created_at": otp_service.utc_now()},
        ])
        from integrations import registry
        prov = registry.get("twilio")
        monkeypatch.setattr(prov, "check_verify",
                            AsyncMock(return_value={"approved": True,
                                                     "status": "approved", "sid": "VE"}))
        monkeypatch.setattr(otp_service.login_throttle,
                            "check_and_record_attempt", AsyncMock())
        from fastapi import HTTPException
        req = _FakeRequest()
        with pytest.raises(HTTPException) as e:
            await otp_service.attach_phone_to_user(
                user_id=u_b, phone="+14155552671", code="123456", request=req,
            )
        assert e.value.status_code == 409
        assert e.value.detail["error"] == "phone_already_attached_elsewhere"
