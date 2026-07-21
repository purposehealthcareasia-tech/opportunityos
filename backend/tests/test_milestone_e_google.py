"""Milestone E — Google Sign-In (Emergent-managed) regression.

Coverage:
  1. `GoogleAuthProvider.describe()` — Emergent-managed → not
     CONFIGURATION_REQUIRED by default; flips to CONFIGURATION_REQUIRED when
     `GOOGLE_AUTH_ENABLED=false`.
  2. Backend consent-first invariant: `start_google_session()` MUST NOT
     create a user row for an unknown email — it returns a pending signup
     handle instead.
  3. Backend linking: existing user with matching email gets linked and
     logged in on Google flow.
  4. Backend hard-fail: invalid session_id → 401.
  5. Sensitive tokens never surface in the API response.

Sync `pymongo` is used for setup + cleanup so we do not tangle with
motor's event-loop binding across async tests. Emergent's session-data
endpoint is monkeypatched with a stub `httpx.AsyncClient`.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from pymongo import MongoClient


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "opportunityos")


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    from integrations import registry
    registry.load_all()
    yield


@pytest.fixture(scope="module")
def sync_db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


# ---------------------------------------------------------------------------
# Provider status
# ---------------------------------------------------------------------------
class TestGoogleAuthProviderStatus:
    def test_default_is_test_mode_or_connected(self):
        from integrations import registry
        p = registry.get("google_auth")
        assert p is not None
        d = p.describe()
        assert d["status"] in ("CONNECTED", "TEST_MODE"), d
        assert d["missing_env"] == []

    def test_disabled_by_env_reports_configuration_required(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_AUTH_ENABLED", "false")
        from integrations import registry
        p = registry.get("google_auth")
        p.configure()
        try:
            d = p.describe()
            assert d["status"] == "CONFIGURATION_REQUIRED", d
        finally:
            monkeypatch.setenv("GOOGLE_AUTH_ENABLED", "true")
            p.configure()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _MockRequest:
    def __init__(self):
        class _Client:
            host = "127.0.0.1"
        self.client = _Client()
        self.headers = {"user-agent": "milestone-e-test"}


class _MockResponse:
    def __init__(self):
        self.cookies_set = {}
    def set_cookie(self, key, value, **kw):
        self.cookies_set[key] = value
    def delete_cookie(self, name, path="/"):
        self.cookies_set.pop(name, None)


def _patch_emergent(monkeypatch, *, payload: dict | None = None,
                     status_code: int = 200):
    from domains.auth import google_service

    class _StubAsyncClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, headers=None):
            assert url == google_service.EMERGENT_SESSION_DATA_URL
            assert headers and headers.get("X-Session-ID")
            body = payload or {}
            req = httpx.Request("GET", url)
            return httpx.Response(status_code, json=body, request=req)

    monkeypatch.setattr(google_service.httpx, "AsyncClient", _StubAsyncClient)


def _run(coro):
    """Run a coroutine on a fresh loop and reset the Motor cache so the next
    test can bind cleanly (Motor caches its loop reference)."""
    from core import db as db_mod
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        # Force Motor client to be re-created on the next `get_db()` call.
        try:
            db_mod._client = None  # type: ignore[attr-defined]
            db_mod._db = None      # type: ignore[attr-defined]
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Backend end-to-end tests
# ---------------------------------------------------------------------------
class TestStartGoogleSession:
    def test_unknown_email_returns_pending_and_creates_no_user(self, monkeypatch, sync_db):
        email = f"new-user-{uuid.uuid4().hex[:8]}@example.com"
        provider_uid = f"gsub-{uuid.uuid4().hex[:12]}"
        _patch_emergent(monkeypatch, payload={
            "id": provider_uid, "email": email, "name": "New User",
            "picture": "https://example.com/pic.png",
            "session_token": "SHOULD_NEVER_LEAK",
        })
        sync_db.login_throttle.delete_many({})

        from domains.auth import google_service
        req, resp = _MockRequest(), _MockResponse()
        result = _run(google_service.start_google_session(
            session_id="fake-sid-" + uuid.uuid4().hex, request=req, response=resp,
        ))
        assert result["status"] == "pending_consent"
        assert result["email"] == email
        assert "SHOULD_NEVER_LEAK" not in json.dumps(result)
        # No user row created yet — consent-first invariant.
        assert sync_db.users.find_one({"email": email}) is None
        # Pending row exists.
        assert sync_db.pending_google_signups.find_one({"id": result["pending_signup_id"]})
        # No session cookie yet.
        assert "oppos_session" not in resp.cookies_set
        # Cleanup.
        sync_db.pending_google_signups.delete_one({"id": result["pending_signup_id"]})

    def test_existing_email_gets_linked_and_logged_in(self, monkeypatch, sync_db):
        from core.security import hash_password

        email = f"linkme-{uuid.uuid4().hex[:8]}@example.com"
        user_id = str(uuid.uuid4())
        sync_db.users.insert_one({
            "id": user_id, "email": email,
            "password_hash": hash_password("SomePass!123"),
            "name": "Existing User", "passport_activated": False,
            "created_at": datetime.now(timezone.utc),
        })
        provider_uid = f"gsub-{uuid.uuid4().hex[:12]}"
        _patch_emergent(monkeypatch, payload={
            "id": provider_uid, "email": email, "name": "Existing User",
            "picture": None, "session_token": "LEAK_GUARD",
        })
        sync_db.login_throttle.delete_many({})

        from domains.auth import google_service
        req, resp = _MockRequest(), _MockResponse()
        result = _run(google_service.start_google_session(
            session_id="fake-sid-" + uuid.uuid4().hex, request=req, response=resp,
        ))
        assert result["status"] == "logged_in"
        assert result["user"]["id"] == user_id
        assert "LEAK_GUARD" not in json.dumps(result, default=str)
        # Link row exists.
        link = sync_db.linked_auth_identities.find_one({
            "provider": "google", "provider_user_id": provider_uid,
        })
        assert link is not None and link["user_id"] == user_id
        # Session cookie set.
        assert "oppos_session" in resp.cookies_set
        # Cleanup.
        sync_db.users.delete_one({"id": user_id})
        sync_db.linked_auth_identities.delete_one({"user_id": user_id})
        sync_db.sessions.delete_many({"user_id": user_id})

    def test_invalid_session_id_hardfails(self, monkeypatch, sync_db):
        from domains.auth import google_service
        from fastapi import HTTPException

        _patch_emergent(monkeypatch, status_code=401,
                          payload={"error": "invalid_session"})
        sync_db.login_throttle.delete_many({})

        req, resp = _MockRequest(), _MockResponse()
        with pytest.raises(HTTPException) as ei:
            _run(google_service.start_google_session(
                session_id="bad-sid-" + uuid.uuid4().hex,
                request=req, response=resp,
            ))
        assert ei.value.status_code == 401


class TestCompleteGoogleSignup:
    def test_missing_required_consent_rejected(self, sync_db):
        from domains.auth import google_service
        from fastapi import HTTPException

        pending_id = str(uuid.uuid4())
        provider_uid = f"gsub-{uuid.uuid4().hex[:12]}"
        email = f"consent-{uuid.uuid4().hex[:8]}@example.com"
        now = datetime.now(timezone.utc)
        sync_db.pending_google_signups.insert_one({
            "id": pending_id, "provider": "google", "provider_user_id": provider_uid,
            "email": email, "name": "Consent Missing", "picture": None,
            "created_at": now, "expires_at": now + timedelta(minutes=15),
        })
        try:
            req, resp = _MockRequest(), _MockResponse()
            with pytest.raises(HTTPException) as ei:
                _run(google_service.complete_google_signup(
                    pending_signup_id=pending_id,
                    consents={"discover_jobs": True},
                    policy_text_version="1.0",
                    request=req, response=resp,
                ))
            assert ei.value.status_code == 400
            assert ei.value.detail["error"] == "required_consent_missing"
        finally:
            sync_db.pending_google_signups.delete_one({"id": pending_id})

    def test_happy_path_creates_user_and_logs_in(self, sync_db):
        from domains.auth import google_service

        pending_id = str(uuid.uuid4())
        provider_uid = f"gsub-{uuid.uuid4().hex[:12]}"
        email = f"happy-{uuid.uuid4().hex[:8]}@example.com"
        now = datetime.now(timezone.utc)
        sync_db.pending_google_signups.insert_one({
            "id": pending_id, "provider": "google", "provider_user_id": provider_uid,
            "email": email, "name": "Happy Path", "picture": None,
            "created_at": now, "expires_at": now + timedelta(minutes=15),
        })
        try:
            req, resp = _MockRequest(), _MockResponse()
            result = _run(google_service.complete_google_signup(
                pending_signup_id=pending_id,
                consents={
                    "process_career_data": True, "discover_jobs": True,
                    "generate_materials": False, "track_applications": False,
                    "email_me": False,
                },
                policy_text_version="1.0",
                request=req, response=resp,
            ))
            assert result["status"] == "signed_up"
            user = sync_db.users.find_one({"email": email})
            assert user is not None
            link = sync_db.linked_auth_identities.find_one({
                "provider": "google", "provider_user_id": provider_uid,
            })
            assert link is not None
            # Consent ledger populated.
            n = sync_db.consent_records.count_documents({"user_id": user["id"]})
            assert n >= 2
            # Session cookie set.
            assert "oppos_session" in resp.cookies_set
            # Cleanup.
            sync_db.users.delete_one({"id": user["id"]})
            sync_db.linked_auth_identities.delete_one({"user_id": user["id"]})
            sync_db.sessions.delete_many({"user_id": user["id"]})
            sync_db.consent_records.delete_many({"user_id": user["id"]})
        finally:
            sync_db.pending_google_signups.delete_one({"id": pending_id})
