"""Regression test for SEC-004(e) — 422 password/credential echo.

Verifies that FastAPI's RequestValidationError responses never contain
plaintext values for keys in the sensitive denylist. Covers:
  * signup missing required fields → 422 with password not echoed
  * signup wrong types on sensitive fields → 422 with password not echoed
  * login missing required fields → 422 with password not echoed
  * nested dicts scrubbed recursively
  * non-sensitive fields preserved for debuggability
"""
from __future__ import annotations
import json
import pytest
import requests
import os

BASE = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "http://localhost:8001",
).rstrip("/")

SECRET = "H3re-15-a-secret-password-that-Must-Not-Leak-!!"


def _post(path: str, body: dict) -> tuple[int, dict]:
    r = requests.post(f"{BASE}{path}", json=body, timeout=15)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text}


def _flatten(obj):
    """Yield every string leaf in a nested JSON structure."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _flatten(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _flatten(v)


class TestValidationScrub:

    def test_signup_missing_fields_scrubs_password(self):
        # missing `consents` + `policy_text_version` triggers 422
        code, body = _post("/api/v1/auth/signup", {
            "email": "leak-probe-1@example.test",
            "password": SECRET,
            "name": "Leak Probe",
        })
        assert code == 422, body
        # SECRET must NOT appear anywhere in the response body
        haystack = json.dumps(body)
        assert SECRET not in haystack, "422 leaked plaintext password"
        # And any surviving `input` entry must have password redacted
        for err in body.get("detail", []):
            if isinstance(err, dict) and isinstance(err.get("input"), dict):
                assert err["input"].get("password") == "<redacted>"

    def test_signup_wrong_types_scrubs_password(self):
        code, body = _post("/api/v1/auth/signup", {
            "email": 42,               # wrong type
            "password": SECRET,        # right type, but should still be scrubbed on error
            "name": None,              # wrong type
            "consents": "not-a-dict",  # wrong type
            "policy_text_version": 1.0,
        })
        assert code == 422, body
        assert SECRET not in json.dumps(body)

    def test_login_missing_fields_scrubs_password(self):
        code, body = _post("/api/v1/auth/login", {"password": SECRET})
        assert code == 422, body
        assert SECRET not in json.dumps(body)

    def test_all_denylisted_keys_scrubbed(self):
        """Non-existent endpoint won't 422, so hit signup with every
        sensitive key present at once via wrong-shape body."""
        payload = {
            "email": None,  # wrong type -> triggers 422
            "password": SECRET,
            "password_hash": "hash-that-must-not-leak",
            "token": "token-that-must-not-leak",
            "otp": "123456",
            "code": "auth-code-that-must-not-leak",
            "session_id": "sess-that-must-not-leak",
            "refresh_token": "refresh-that-must-not-leak",
        }
        code, body = _post("/api/v1/auth/signup", payload)
        assert code == 422, body
        hay = json.dumps(body)
        for sensitive_value in (
            SECRET, "hash-that-must-not-leak", "token-that-must-not-leak",
            "123456", "auth-code-that-must-not-leak",
            "sess-that-must-not-leak", "refresh-that-must-not-leak",
        ):
            assert sensitive_value not in hay, f"422 leaked value for sensitive key: {sensitive_value!r}"

    def test_non_sensitive_fields_preserved(self):
        """Debuggability: non-sensitive keys like 'email' should still appear
        (rediscoverable) so callers can pinpoint what to fix."""
        code, body = _post("/api/v1/auth/signup", {
            "email": "not-actually-secret@example.test",
            "password": SECRET,
            "name": "Debug",
        })
        assert code == 422
        # email is a NON-sensitive field and must NOT be redacted
        assert "not-actually-secret@example.test" in json.dumps(body)
        # password value still must not leak
        assert SECRET not in json.dumps(body)

    def test_nested_dict_scrubbed_recursively(self):
        """If a nested container contains a denylisted key it must also be scrubbed."""
        code, body = _post("/api/v1/auth/signup", {
            "email": 12345,  # wrong type triggers 422 with 'input' echo
            "password": SECRET,
            "consents": {
                "process_career_data": True,
                # denylisted keys smuggled inside a nested container:
                "password": SECRET,
                "sub": {"token": "leaky-token"},
            },
            "policy_text_version": "1.0",
        })
        assert code == 422, body
        hay = json.dumps(body)
        assert SECRET not in hay, "nested password leaked"
        assert "leaky-token" not in hay, "nested token leaked"
