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
