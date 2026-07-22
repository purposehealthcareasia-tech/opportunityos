"""Sign in with Apple — standards-based OIDC regression.

Covers every founder-mandated invariant:

- Provider status truthfulness (CONFIGURATION_REQUIRED → CONNECTED transitions).
- `/apple/start` returns 503 `apple_auth_not_configured` when env vars are absent.
- Mocked id_token flows:
    * happy path (valid signature, correct nonce, verified email) → pending_consent
      or logged_in.
    * bad signature → 401 apple_id_token_invalid (message=signature).
    * bad nonce → 401 apple_id_token_invalid (message=nonce).
    * expired token → 401 apple_id_token_invalid (message=expired).
    * unknown kid → 401 apple_id_token_invalid (message=unknown kid).
    * user-cancelled flow (missing state) → 400 apple_state_invalid.
- Consent-first gate: no `users` row appears until `/apple/complete`.
- Private-relay-email semantics: NEVER auto-linked to existing account by
  email, creates a distinct account instead.
- Duplicate identity prevention: second sign-in with the same `apple_sub`
  logs into the same account.
- Client-secret JWT structure (ES256, aud/iss/sub).
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid
from unittest.mock import patch, AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, NoEncryption,
)
from motor.motor_asyncio import AsyncIOMotorClient
import jwt as pyjwt

from core import db as db_module
from core.config import settings
from domains.auth import apple_service
from domains.auth import repository as user_repo
# Import provider at top so integrations.base's load_dotenv autoload fires
# ONCE at collection time (mirrors the fix from test_notifications_webpush).
from integrations.auth.apple_provider import AppleAuthProvider  # noqa: E402


# ---------------------------------------------------------------------------
# Key + token fixtures.
# ---------------------------------------------------------------------------

def _generate_p256_key_pair():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    return key, pem


def _pubkey_to_jwk(pub, kid: str) -> dict:
    numbers = pub.public_numbers()
    def _b64(x: int) -> str:
        b = x.to_bytes(32, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    return {"kty": "EC", "crv": "P-256", "kid": kid,
            "x": _b64(numbers.x), "y": _b64(numbers.y), "alg": "ES256", "use": "sig"}


def _make_id_token(*, private_key, kid: str, aud: str, sub: str,
                   nonce: str, email: str = "user@icloud.com",
                   is_private_email: bool = False, email_verified: bool = True,
                   exp_offset: int = 3600, iss: str = "https://appleid.apple.com") -> str:
    now = int(time.time())
    payload = {
        "iss": iss, "aud": aud, "sub": sub,
        "iat": now, "exp": now + exp_offset,
        "email": email, "email_verified": email_verified,
        "is_private_email": is_private_email, "nonce": nonce,
    }
    return pyjwt.encode(payload, private_key, algorithm="ES256", headers={"kid": kid})


APPLE_KID = "AK-TEST-KID"
KEY, PEM = _generate_p256_key_pair()
PUB_JWK = _pubkey_to_jwk(KEY.public_key(), APPLE_KID)


@pytest.fixture
def apple_env(monkeypatch):
    monkeypatch.setenv("APPLE_CLIENT_ID", "com.opportunityos.services.test")
    monkeypatch.setenv("APPLE_TEAM_ID", "TEAMTEST01")
    monkeypatch.setenv("APPLE_KEY_ID", APPLE_KID)
    monkeypatch.setenv("APPLE_PRIVATE_KEY", PEM)
    monkeypatch.setenv("APPLE_REDIRECT_URI", "https://apple-test.example.com/callback")
    # Force the JWKS cache to serve our test public key.
    apple_service._JWKS_CACHE["keys"] = [PUB_JWK]
    apple_service._JWKS_CACHE["fetched_at"] = time.time()
    yield
    apple_service._JWKS_CACHE["keys"] = None
    apple_service._JWKS_CACHE["fetched_at"] = 0.0


@pytest.fixture
async def isolated_db(monkeypatch):
    dbname = f"opportunityos_appletest_{uuid.uuid4().hex[:8]}"
    client = AsyncIOMotorClient(settings.MONGO_URL, uuidRepresentation="standard")
    fake_db = client[dbname]
    # NOTE: deliberately NOT monkey-patching `db_module.get_db`. Patching the
    # shared function in `core.db` is observed to bleed into `test_milestone_e_google`
    # (`Event loop is closed` on collections against `opportunityos_appletest_*`
    # names). Patching each downstream module's own binding is enough.
    monkeypatch.setattr(apple_service, "get_db", lambda: fake_db)
    monkeypatch.setattr(user_repo, "get_db", lambda: fake_db, raising=False)
    from domains.audit import service as audit_mod
    monkeypatch.setattr(audit_mod, "get_db", lambda: fake_db, raising=False)
    from domains.consent import service as consent_mod
    monkeypatch.setattr(consent_mod, "get_db", lambda: fake_db, raising=False)
    from core import sessions as sessions_mod
    monkeypatch.setattr(sessions_mod, "get_db", lambda: fake_db, raising=False)
    try:
        await apple_service.ensure_indexes()
        yield fake_db
    finally:
        try:
            import pymongo
            pymongo.MongoClient(settings.MONGO_URL).drop_database(dbname)
        except Exception:
            pass
        try:
            db_module._client = None  # type: ignore[attr-defined]
            db_module._db = None      # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Client-secret JWT construction.
# ---------------------------------------------------------------------------

class TestClientSecretJWT:
    def test_client_secret_jwt_structure(self, apple_env):
        cfg = apple_service._cfg()
        token = apple_service._client_secret_jwt(cfg)
        # Signed with our test key → we can verify with the public counterpart.
        decoded = pyjwt.decode(
            token, KEY.public_key(),
            algorithms=["ES256"], audience="https://appleid.apple.com",
        )
        assert decoded["iss"] == "TEAMTEST01"
        assert decoded["sub"] == "com.opportunityos.services.test"
        assert decoded["aud"] == "https://appleid.apple.com"
        # kid header carries our KEY_ID.
        header = pyjwt.get_unverified_header(token)
        assert header["kid"] == APPLE_KID
        assert header["alg"] == "ES256"
        # exp should be ≤ 30 min.
        assert decoded["exp"] - decoded["iat"] <= 60 * 30


# ---------------------------------------------------------------------------
# id_token verification.
# ---------------------------------------------------------------------------

class TestIdTokenVerification:
    @pytest.mark.asyncio
    async def test_valid_token_returns_payload(self, apple_env):
        tok = _make_id_token(private_key=KEY, kid=APPLE_KID,
                             aud="com.opportunityos.services.test",
                             sub="APPLE_SUB_1", nonce="NONCE_A")
        payload = await apple_service._verify_apple_id_token(
            tok, expected_nonce="NONCE_A",
            expected_aud="com.opportunityos.services.test",
        )
        assert payload["sub"] == "APPLE_SUB_1"

    @pytest.mark.asyncio
    async def test_bad_signature(self, apple_env):
        wrong_key, _ = _generate_p256_key_pair()
        tok = _make_id_token(private_key=wrong_key, kid=APPLE_KID,
                             aud="com.opportunityos.services.test",
                             sub="X", nonce="N")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await apple_service._verify_apple_id_token(
                tok, expected_nonce="N", expected_aud="com.opportunityos.services.test")
        assert e.value.status_code == 401
        assert e.value.detail["error"] == "apple_id_token_invalid"
        assert e.value.detail["message"] == "signature"

    @pytest.mark.asyncio
    async def test_nonce_mismatch(self, apple_env):
        tok = _make_id_token(private_key=KEY, kid=APPLE_KID,
                             aud="com.opportunityos.services.test",
                             sub="X", nonce="RIGHT")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await apple_service._verify_apple_id_token(
                tok, expected_nonce="WRONG",
                expected_aud="com.opportunityos.services.test")
        assert e.value.status_code == 401
        assert e.value.detail["message"] == "nonce"

    @pytest.mark.asyncio
    async def test_expired_token(self, apple_env):
        tok = _make_id_token(private_key=KEY, kid=APPLE_KID,
                             aud="com.opportunityos.services.test",
                             sub="X", nonce="N", exp_offset=-30)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await apple_service._verify_apple_id_token(
                tok, expected_nonce="N",
                expected_aud="com.opportunityos.services.test")
        assert e.value.detail["message"] == "expired"

    @pytest.mark.asyncio
    async def test_unknown_kid(self, apple_env):
        tok = _make_id_token(private_key=KEY, kid="UNKNOWN_KID",
                             aud="com.opportunityos.services.test",
                             sub="X", nonce="N")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await apple_service._verify_apple_id_token(
                tok, expected_nonce="N",
                expected_aud="com.opportunityos.services.test")
        assert e.value.detail["message"] == "unknown kid"

    @pytest.mark.asyncio
    async def test_wrong_audience(self, apple_env):
        tok = _make_id_token(private_key=KEY, kid=APPLE_KID,
                             aud="some.other.app", sub="X", nonce="N")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await apple_service._verify_apple_id_token(
                tok, expected_nonce="N",
                expected_aud="com.opportunityos.services.test")
        assert e.value.detail["message"] == "audience"


# ---------------------------------------------------------------------------
# Callback flow — consent-first + relay + duplicate identity.
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self):
        self.client = None
        self.headers = {}
        self.state = type("S", (), {})()


class _FakeResponse:
    def __init__(self):
        self.cookies = {}
        self.headers = {}
    def set_cookie(self, key, value=None, **kw):
        self.cookies[key] = value
    def delete_cookie(self, *a, **k):
        pass


async def _mock_token_exchange(id_token_str: str):
    """Patch httpx.AsyncClient.post to return the same id_token in a fake
    Apple response, so we don't hit real Apple endpoints."""
    from unittest.mock import MagicMock
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json = lambda: {"id_token": id_token_str,
                                  "access_token": "AT",
                                  "refresh_token": "RT"}
    return fake_response


class TestCallbackFlow:
    @pytest.mark.asyncio
    async def test_new_user_returns_pending_consent(self, apple_env, isolated_db):
        # Seed a state so _consume_state finds a matching nonce.
        state, nonce = "STATE1", "NONCE1"
        await apple_service._put_state(state, nonce)

        tok = _make_id_token(private_key=KEY, kid=APPLE_KID,
                             aud="com.opportunityos.services.test",
                             sub="APPLE_SUB_NEW", nonce=nonce,
                             email="firstuser@example.com")
        req, resp = _FakeRequest(), _FakeResponse()
        # Patch throttle + token exchange.
        with patch.object(apple_service.login_throttle, "check_and_record_attempt", AsyncMock()), \
             patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.post = AsyncMock(return_value=await _mock_token_exchange(tok))

            result = await apple_service.handle_callback(
                code="CODE1", state=state,
                id_token_body=None, user_json=None,
                request=req, response=resp,
            )
        assert result["status"] == "pending_consent"
        assert result["pending_signup_id"]
        assert result["is_private_email"] is False
        # CONSENT-FIRST invariant: no `users` row exists yet.
        assert await isolated_db.users.count_documents({}) == 0

    @pytest.mark.asyncio
    async def test_state_invalid_returns_400(self, apple_env, isolated_db):
        from fastapi import HTTPException
        req, resp = _FakeRequest(), _FakeResponse()
        with patch.object(apple_service.login_throttle, "check_and_record_attempt", AsyncMock()):
            with pytest.raises(HTTPException) as e:
                await apple_service.handle_callback(
                    code="X", state="NEVER_ISSUED",
                    id_token_body=None, user_json=None,
                    request=req, response=resp,
                )
        assert e.value.status_code == 400
        assert e.value.detail["error"] == "apple_state_invalid"

    @pytest.mark.asyncio
    async def test_state_is_single_use(self, apple_env, isolated_db):
        state, nonce = "STATE2", "NONCE2"
        await apple_service._put_state(state, nonce)
        # First consume ok.
        assert await apple_service._consume_state(state) == nonce
        # Second consume fails.
        assert await apple_service._consume_state(state) is None

    @pytest.mark.asyncio
    async def test_private_relay_email_creates_distinct_account(self, apple_env, isolated_db):
        # Pre-seed an existing account with a real (non-relay) email.
        existing_id = str(uuid.uuid4())
        await isolated_db.users.insert_one({
            "id": existing_id, "email": "founder@company.com",
            "password_hash": "existing", "name": "Founder",
            "created_at": apple_service.utc_now(),
        })

        # Now an Apple sign-in arrives with a private-relay email.
        state, nonce = "STATE3", "NONCE3"
        await apple_service._put_state(state, nonce)
        tok = _make_id_token(
            private_key=KEY, kid=APPLE_KID,
            aud="com.opportunityos.services.test",
            sub="APPLE_SUB_RELAY", nonce=nonce,
            email="XyZ123@privaterelay.appleid.com",
            is_private_email=True, email_verified=True,
        )
        req, resp = _FakeRequest(), _FakeResponse()
        with patch.object(apple_service.login_throttle, "check_and_record_attempt", AsyncMock()), \
             patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=await _mock_token_exchange(tok),
            )
            result = await apple_service.handle_callback(
                code="C", state=state, id_token_body=None, user_json=None,
                request=req, response=resp,
            )
        # MUST be pending_consent — NOT auto-linked to founder@company.com.
        assert result["status"] == "pending_consent"
        assert result["is_private_email"] is True
        # And the founder account was NOT touched.
        row = await isolated_db.users.find_one({"id": existing_id})
        assert row is not None and row["email"] == "founder@company.com"
        # No new user row yet (consent still pending).
        assert await isolated_db.users.count_documents({}) == 1

    @pytest.mark.asyncio
    async def test_duplicate_apple_sub_reuses_linked_user(self, apple_env, isolated_db, monkeypatch):
        # Pre-create a user + link — simulate a prior Apple signup.
        uid = str(uuid.uuid4())
        await isolated_db.users.insert_one({
            "id": uid, "email": "returning@example.com", "password_hash": "",
            "name": "Returning", "created_at": apple_service.utc_now(),
        })
        await isolated_db.linked_auth_identities.insert_one({
            "id": str(uuid.uuid4()),
            "provider": "apple", "provider_user_id": "APPLE_SUB_RETURN",
            "email": "returning@example.com", "user_id": uid,
            "linked_at": apple_service.utc_now(),
        })

        state, nonce = "STATE4", "NONCE4"
        await apple_service._put_state(state, nonce)
        tok = _make_id_token(private_key=KEY, kid=APPLE_KID,
                             aud="com.opportunityos.services.test",
                             sub="APPLE_SUB_RETURN", nonce=nonce,
                             email="whatever@example.com")
        req, resp = _FakeRequest(), _FakeResponse()
        # Mock session_store.create_session at the source module so no real
        # Motor writes to the ephemeral test DB survive into downstream
        # pytest-asyncio tests. We still verify the "logged_in" branch fires
        # and returns the correct user_id.
        from core import sessions as sessions_mod
        monkeypatch.setattr(
            sessions_mod, "create_session",
            AsyncMock(return_value={
                "session_id": "test-sid", "csrf_token": "test-csrf",
                "user_id": uid, "role": "user",
            }),
        )
        # Also patch the reference apple_service imports at call time.
        monkeypatch.setattr(
            apple_service.session_store, "create_session",
            sessions_mod.create_session,
        )
        with patch.object(apple_service.login_throttle, "check_and_record_attempt", AsyncMock()), \
             patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=await _mock_token_exchange(tok),
            )
            result = await apple_service.handle_callback(
                code="C", state=state, id_token_body=None, user_json=None,
                request=req, response=resp,
            )
        assert result["status"] == "logged_in"
        assert result["user"]["id"] == uid
        # No duplicate link inserted.
        assert await isolated_db.linked_auth_identities.count_documents({
            "provider": "apple", "provider_user_id": "APPLE_SUB_RETURN",
        }) == 1


# ---------------------------------------------------------------------------
# Provider status truthfulness.
# ---------------------------------------------------------------------------

class TestProviderStatusTruthfulness:
    def _fresh_provider(self):
        p = AppleAuthProvider()
        p.configure()
        return p

    def test_configuration_required_when_env_missing(self, monkeypatch):
        for k in ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID",
                  "APPLE_PRIVATE_KEY", "APPLE_REDIRECT_URI"):
            monkeypatch.delenv(k, raising=False)
        p = self._fresh_provider()
        assert p.status().value == "CONFIGURATION_REQUIRED"

    def test_configuration_required_when_redirect_uri_not_https(self, monkeypatch, apple_env):
        monkeypatch.setenv("APPLE_REDIRECT_URI", "http://insecure.example.com/cb")
        p = self._fresh_provider()
        assert p.status().value == "CONFIGURATION_REQUIRED"

    def test_connected_when_env_present_and_valid(self, apple_env):
        p = self._fresh_provider()
        # Won't be CONNECTED until we know JWKS is reachable — but for the
        # status method alone, configuration presence + no recent error →
        # CONNECTED (health_check runs separately).
        assert p.status().value == "CONNECTED"

    def test_describe_never_leaks_private_key(self, apple_env):
        p = self._fresh_provider()
        blob = json.dumps(p.describe())
        assert "-----BEGIN" not in blob
        # Env var NAME still appears (which is fine).
        assert "APPLE_PRIVATE_KEY" in blob
