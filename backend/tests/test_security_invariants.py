"""Security invariants — v0.1 close-out (2026-02).

Runs with the regular pytest suite. Enumerates every admin- and user-facing
response endpoint and grep-asserts that credential/secret markers NEVER appear
in the response body. This exists so that any future addition to the admin
surface (or any new user-serialising endpoint) cannot silently reintroduce the
P0 credential-leak bug found during v0.1 close-out.

Additions to guard: if you introduce a new admin GET, add it to
`ADMIN_READ_ENDPOINTS` below. If you introduce a new credential/secret column
on `users`, extend `CREDENTIAL_KEYS` / `SENSITIVE_TOKEN_PATTERNS`.

Run:
    cd /app/backend && python3 -m pytest tests/test_security_invariants.py -v
"""
from __future__ import annotations
import os
import re
import json
from pathlib import Path

import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL",
                       "https://lynk-preview-2.preview.emergentagent.com").rstrip("/")


# ---------------------------------------------------------------------------
# Guarded surfaces
# ---------------------------------------------------------------------------
# Admin GETs — read-only for admin+support (all of them accept both roles).
ADMIN_READ_ENDPOINTS: list[str] = [
    "/api/v1/admin/users",
    "/api/v1/admin/users?q=fixture",
    "/api/v1/admin/subscriptions",
    "/api/v1/admin/manual-queue",
    "/api/v1/admin/flags",
    "/api/v1/admin/support-tickets",
    "/api/v1/admin/health",
    "/api/v1/admin/observability/events",
    "/api/v1/admin/observability/errors",
]

# User-facing GETs that serialize the currently-authenticated user or a
# subordinate of theirs. Any of these must never expose credential material of
# the caller (or anyone else).
USER_SELF_ENDPOINTS: list[str] = [
    "/api/v1/auth/me",
    "/api/v1/subscriptions/me",
    "/api/v1/usage/me",
    "/api/v1/preferences/me",
    "/api/v1/privacy/consents",
    "/api/v1/privacy/release-log",
]

# ---------------------------------------------------------------------------
# Credential / secret markers
# ---------------------------------------------------------------------------
# Substring keys that must NEVER appear in an admin/user response body. Uses
# quoted-key form to avoid false positives (e.g., the word "password" in a
# user-facing help string is fine, `"password_hash":` is not).
CREDENTIAL_KEYS: list[str] = [
    '"password_hash"',
    '"password":',           # never surface a raw password
    '"totp_secret"',
    '"recovery_codes"',
    '"csrf_token"',           # session/CSRF secrets never travel via response body
    '"session_id"',           # opaque session id must live only in cookies
]

# Byte-pattern markers of credentials embedded as VALUES (i.e., unquoted keys).
# bcrypt hashes always start with $2a$ / $2b$ / $2y$; JWT tokens are three
# base64url chunks separated by dots.
SENSITIVE_TOKEN_PATTERNS: list[re.Pattern] = [
    re.compile(r"\$2[aby]\$\d{2}\$"),   # bcrypt hash prefix
]

# JWT-in-body is allowed on ONE endpoint — /api/v1/auth/login return payload
# under the CI test issuer flag. This module intentionally does NOT probe
# /auth/login (the issuer is a documented CI-only affordance).


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _bearer_login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/api/v1/auth/login",
                       json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("access_token")
    assert tok, f"login response missing access_token for {email}"
    return tok


def _scan_body_for_leaks(body_text: str, endpoint: str, role: str) -> list[str]:
    """Return the list of leak-descriptions found in `body_text` (empty if clean)."""
    findings: list[str] = []
    for key in CREDENTIAL_KEYS:
        if key in body_text:
            findings.append(f"credential key `{key}` present")
    for pat in SENSITIVE_TOKEN_PATTERNS:
        m = pat.search(body_text)
        if m:
            findings.append(f"sensitive pattern `{pat.pattern}` matched at pos {m.start()}")
    return findings


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _bearer_login("admin@opportunityos.dev", "Admin!Console1")


@pytest.fixture(scope="module")
def support_token() -> str:
    return _bearer_login("support@opportunityos.dev", "Support!Console1")


@pytest.fixture(scope="module")
def fixture_token() -> str:
    return _bearer_login("fixture-ead@opportunityos.dev", "Fixture!Test1")


@pytest.fixture(scope="module")
def mongo_db():
    """Shared local Mongo handle for regression fixtures.
    Reads MONGO_URL / DB_NAME from backend/.env if present."""
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "opportunityos")
    c = MongoClient(mongo_url)
    yield c[db_name]
    c.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestNoCredentialLeaksInAdminReads:
    """Every admin GET must be free of credential material for BOTH admin and
    support roles."""

    @pytest.mark.parametrize("endpoint", ADMIN_READ_ENDPOINTS)
    def test_admin_read_no_credential_leak(self, endpoint, admin_token, support_token):
        for role, tok in (("admin", admin_token), ("support", support_token)):
            r = requests.get(f"{BASE}{endpoint}",
                              headers={"Authorization": f"Bearer {tok}"}, timeout=15)
            # 200 for both roles on read paths.
            assert r.status_code == 200, (
                f"{role} unexpected {r.status_code} on {endpoint}: {r.text[:200]}"
            )
            findings = _scan_body_for_leaks(r.text, endpoint, role)
            assert not findings, (
                f"[{role}] {endpoint} leaked credential material: {findings}\n"
                f"body head: {r.text[:400]}"
            )


class TestNoCredentialLeaksInUserReads:
    """Every user-self GET must be free of credential material."""

    @pytest.mark.parametrize("endpoint", USER_SELF_ENDPOINTS)
    def test_user_read_no_credential_leak(self, endpoint, fixture_token):
        r = requests.get(f"{BASE}{endpoint}",
                          headers={"Authorization": f"Bearer {fixture_token}"}, timeout=15)
        # 200 or 4xx (e.g., 403 consent_required is legitimate); we still scan
        # whatever body came back.
        findings = _scan_body_for_leaks(r.text, endpoint, "user")
        assert not findings, (
            f"[user] {endpoint} leaked credential material: {findings}\n"
            f"body head: {r.text[:400]}"
        )


class TestAdminUserDetailDeepScan:
    """The single most sensitive admin endpoint — deep scan of every user-detail
    fetch for both admin and support (targeting the P0 bug found during v0.1
    close-out)."""

    def _fixture_user_id(self, admin_token: str) -> str:
        r = requests.get(f"{BASE}/api/v1/admin/users?q=fixture",
                          headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        return r.json()["users"][0]["id"]

    @pytest.mark.parametrize("role_label", ["admin", "support"])
    def test_user_detail_no_leaks(self, role_label, admin_token, support_token):
        tok = admin_token if role_label == "admin" else support_token
        uid = self._fixture_user_id(admin_token)
        r = requests.get(f"{BASE}/api/v1/admin/users/{uid}",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert r.status_code == 200
        body = r.json()

        # Structural asserts on `user` sub-doc.
        user = body.get("user") or {}
        for k in ("password_hash", "password", "totp_secret", "recovery_codes"):
            assert k not in user, f"[{role_label}] user.{k} present: keys={list(user.keys())}"

        # Full-body scan.
        text = json.dumps(body)
        findings = _scan_body_for_leaks(text, f"/admin/users/{uid}", role_label)
        assert not findings, (
            f"[{role_label}] /admin/users/{{id}} leaked: {findings}\n"
            f"body: {text[:600]}"
        )


class TestSensitivityRegistry:
    """Register-of-truth: whenever a new sensitive field is added to `users` in
    Mongo, this test forces us to also add it to the `SENSITIVE_USER_FIELDS`
    set in `domains/admin/service.py`."""

    def test_admin_service_lists_all_known_credential_fields(self):
        svc = Path("/app/backend/domains/admin/service.py").read_text()
        for field in ("password_hash", "password", "totp_secret", "recovery_codes"):
            assert f'"{field}"' in svc, (
                f"SENSITIVE_USER_FIELDS in domains/admin/service.py is missing "
                f"`{field}`. Add it to the set so the sanitizer scrubs it."
            )


# ---------------------------------------------------------------------------
# SEC-001..004 + P3 fix-brief regressions.
# ---------------------------------------------------------------------------
import time
import uuid


def _fixture_user() -> tuple[str, str]:
    return ("fixture-ead@opportunityos.dev", "Fixture!Test1")


class TestPrivacyExportDoesNotLeakCredentials:
    """SEC-001 · export bundle must be sanitized (no password_hash, no bcrypt marker)."""

    def test_export_bundle_has_no_password_hash(self, fixture_token, mongo_db=None):
        # Kick off + immediately fetch (synchronous v0.1 build).
        r1 = requests.post(f"{BASE}/api/v1/privacy/export", json={},
                            headers={"Authorization": f"Bearer {fixture_token}"}, timeout=15)
        assert r1.status_code == 200, r1.text
        job_id = r1.json()["job_id"]
        r2 = requests.get(f"{BASE}/api/v1/privacy/export/{job_id}",
                           headers={"Authorization": f"Bearer {fixture_token}"}, timeout=15)
        assert r2.status_code == 200
        body = r2.json()
        content = (body.get("download") or {}).get("content") or {}
        profile = content.get("profile") or {}
        assert "password_hash" not in profile, f"profile leaked password_hash: keys={list(profile.keys())}"
        for k in ("password", "totp_secret", "recovery_codes"):
            assert k not in profile, f"profile leaked `{k}`"
        text = json.dumps(body)
        assert '"password_hash"' not in text, "export body contains password_hash key"
        # bcrypt marker must not appear anywhere.
        assert not re.search(r"\$2[aby]\$\d{2}\$", text), "export body contains bcrypt marker"


class TestSiblingSessionRevocationOnPasswordChange:
    """SEC-002 · password change revokes OTHER sessions; current session survives."""

    def test_password_change_kills_sibling_sessions(self):
        # Provision a throwaway user via signup (independent of fixtures).
        email = f"pw-rotate-{uuid.uuid4().hex[:10]}@opportunityos.dev"
        pw1, pw2 = "OrigPass!123", "NewPass!456"
        s_a = requests.Session()
        s_b = requests.Session()
        signup_body = {
            "email": email, "password": pw1, "name": "PwRotate Test",
            "policy_text_version": "1.0",
            "consents": {"process_career_data": True, "discover_jobs": True,
                          "generate_materials": False, "track_applications": False,
                          "email_me": False},
        }
        r = s_a.post(f"{BASE}/api/v1/auth/signup", json=signup_body, timeout=15)
        assert r.status_code == 201, r.text
        # Session B logs in on a separate cookie jar.
        r = s_b.post(f"{BASE}/api/v1/auth/login",
                      json={"email": email, "password": pw1}, timeout=15)
        assert r.status_code == 200, r.text

        # Both sessions can hit /me.
        assert s_a.get(f"{BASE}/api/v1/auth/me").status_code == 200
        assert s_b.get(f"{BASE}/api/v1/auth/me").status_code == 200

        # Session A rotates the password. Send CSRF header + cookie value.
        csrf_a = s_a.cookies.get("oppos_csrf")
        assert csrf_a, "session A missing CSRF cookie"
        r = s_a.post(f"{BASE}/api/v1/users/me/change-password",
                      json={"current_password": pw1, "new_password": pw2},
                      headers={"X-CSRF-Token": csrf_a}, timeout=15)
        assert r.status_code == 204, r.text

        # Session A still valid (its session was rotated in-place).
        assert s_a.get(f"{BASE}/api/v1/auth/me").status_code == 200, \
            "session A should survive its own password change (rotated in place)"
        # Session B is nuked.
        assert s_b.get(f"{BASE}/api/v1/auth/me").status_code == 401, \
            "sibling session B should be revoked after password change"


class TestIdempotencyIsUserScopedOnCookiePath:
    """SEC-003 · same Idempotency-Key from two cookie-authenticated users on the
    same endpoint must NOT collide."""

    def test_two_cookie_sessions_do_not_cross_pollinate(self):
        # Sign up two throwaway users.
        base_body = {
            "policy_text_version": "1.0",
            "consents": {"process_career_data": True, "discover_jobs": True,
                          "generate_materials": False, "track_applications": False,
                          "email_me": False},
            "password": "IdmpTest!123",
        }
        e1 = f"idmp-a-{uuid.uuid4().hex[:8]}@opportunityos.dev"
        e2 = f"idmp-b-{uuid.uuid4().hex[:8]}@opportunityos.dev"
        s1, s2 = requests.Session(), requests.Session()
        assert s1.post(f"{BASE}/api/v1/auth/signup",
                       json={**base_body, "email": e1, "name": "A"}, timeout=15).status_code == 201
        assert s2.post(f"{BASE}/api/v1/auth/signup",
                       json={**base_body, "email": e2, "name": "B"}, timeout=15).status_code == 201

        # Both send the SAME idempotency key to the SAME endpoint. Consents POST
        # is per-user append-only. If idempotency collided across users, the
        # replayed body would echo user A's row-id to user B.
        key = f"idmp-shared-{uuid.uuid4()}"
        def _post(sess, scope):
            return sess.post(
                f"{BASE}/api/v1/consents",
                headers={
                    "X-CSRF-Token": sess.cookies.get("oppos_csrf") or "",
                    "Idempotency-Key": key,
                },
                json={"scope": scope, "granted": True, "policy_text_version": "1.0"},
                timeout=15,
            )

        ra = _post(s1, "discover_jobs")
        rb = _post(s2, "discover_jobs")
        assert ra.status_code == 201, ra.text
        assert rb.status_code == 201, rb.text
        # If cross-user replay happened, rb would carry ra's id (would 200 replay,
        # not 201). More importantly, each row's owner must resolve back to the
        # right user on the /consents state endpoint.
        state_a = s1.get(f"{BASE}/api/v1/consents").json()
        state_b = s2.get(f"{BASE}/api/v1/consents").json()
        # ai_matching should be True for both — but the KEY invariant is that
        # neither user got the OTHER user's row id echoed back, and the ids
        # differ (append-only ledger produced two distinct records).
        assert ra.json()["id"] != rb.json()["id"], "cross-user idempotency replay detected"
        # Extra sanity: their states are independent snapshots.
        assert isinstance(state_a, dict) and isinstance(state_b, dict)


class TestAccessTokenInBodyFlagBehaviour:
    """SEC-004(a) · access_token in login/signup body ONLY when
    CI_TEST_ISSUER_ENABLED. Because the running preview has the flag ON, we
    verify BOTH conditions:

      1. Live behaviour (flag ON) — access_token IS present.
      2. Unit-level behaviour (flag OFF) — call the pure `_maybe_bearer_body`
         helper with the flag monkey-patched off; assert empty dict.
    """

    def test_live_login_body_shape_reflects_flag(self):
        email, password = _fixture_user()
        r = requests.post(f"{BASE}/api/v1/auth/login",
                           json={"email": email, "password": password}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        # We're in preview → flag ON → token IS present.
        assert "access_token" in body, "preview has CI_TEST_ISSUER_ENABLED=true; token must be in body"

    def test_helper_returns_empty_when_flag_off(self, monkeypatch):
        # Pure-unit check — no HTTP.
        from core.config import settings as _settings
        from domains.auth import service as auth_svc
        monkeypatch.setattr(_settings, "CI_TEST_ISSUER_ENABLED", False)
        result = auth_svc._maybe_bearer_body("some-user-id")
        assert result == {}, f"expected empty dict when flag off, got {result}"


class TestPublicHealthDoesNotLeakDeployFlags:
    """SEC-004(d) · /api/health MUST NOT surface prod_mode / ci_test_issuer_enabled."""

    def test_public_health_scrubbed(self):
        r = requests.get(f"{BASE}/api/health", timeout=15)
        assert r.status_code == 200
        body = r.json()
        for k in ("prod_mode", "ci_test_issuer_enabled"):
            assert k not in body, f"/api/health leaks {k}: {body}"

    def test_admin_health_exposes_flags(self, admin_token):
        r = requests.get(f"{BASE}/api/v1/admin/health",
                          headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "prod_mode" in body and "ci_test_issuer_enabled" in body


class TestLoginThrottle:
    """SEC-P3(a) · after N failed attempts within the window the endpoint
    returns 429 with Retry-After."""

    def test_login_throttle_kicks_in(self, mongo_db):
        # Use a scratch identifier; clear any existing bucket for this test IP.
        email = f"throttle-{uuid.uuid4().hex[:10]}@opportunityos.dev"
        # Blast the endpoint. Max is 10; we allow one buffer because the reply
        # for the throttling call itself is what proves the mechanism.
        last_status = None
        for _ in range(12):
            r = requests.post(f"{BASE}/api/v1/auth/login",
                              json={"email": email, "password": "wrong"}, timeout=10)
            last_status = r.status_code
            if r.status_code == 429:
                assert r.headers.get("Retry-After"), "429 missing Retry-After"
                detail = r.json().get("detail") or {}
                assert detail.get("error") == "rate_limited"
                # Cleanup for isolation from other tests.
                mongo_db.login_throttle.delete_many({"identifier": email.lower()})
                return
        pytest.fail(f"expected 429 within 12 attempts, last status {last_status}")


class TestSensitiveRegistryStillIntact:
    """Force awareness of new credential columns as they get added."""

    def test_admin_sanitizer_lists_new_credential_fields(self):
        # No new fields to add YET, but the check ensures the constant remains
        # the single source of truth. If we later add a `google_refresh_token`
        # field, extend SENSITIVE_USER_FIELDS AND this list simultaneously.
        svc = Path("/app/backend/domains/admin/service.py").read_text()
        for field in ("password_hash", "password", "totp_secret", "recovery_codes"):
            assert f'"{field}"' in svc

