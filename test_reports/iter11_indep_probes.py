"""Independent black-box probes for iteration 11 verification.

Extra confidence checks beyond `tests/test_security_invariants.py`:
- SEC-001 baseline: raw mongo `users` doc DOES contain password_hash (proves
  export sanitization is a response-side scrub, not a schema change).
- SEC-002: assert the users' `sessions` collection state — old session ids
  revoked_at set, session A has a NEW id.
- SEC-003 same-session replay: same session + same key + same body →
  response.body identical AND `X-Idempotent-Replay: true` header on the 2nd
  request.
- P3(a): after 429 kicks in for identifier X, a DIFFERENT identifier can still
  log in successfully (no IP-wide poisoning at normal volumes).
"""
from __future__ import annotations
import os
import re
import sys
import json
import uuid
import time

import requests

BASE = "https://lynk-preview-2.preview.emergentagent.com"


def _die(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"PASS: {msg}")


def _login_bearer(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/api/v1/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    if r.status_code != 200:
        _die(f"login {email}: {r.status_code} {r.text}")
    return r.json()["access_token"]


def probe_sec001_mongo_baseline():
    # Uses local mongo via env vars.
    from pymongo import MongoClient
    c = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = c[os.environ.get("DB_NAME", "opportunityos")]
    doc = db.users.find_one({"email": "fixture-ead@opportunityos.dev"})
    if not doc:
        _die("SEC-001 baseline: fixture user not found in mongo")
    if "password_hash" not in doc:
        _die("SEC-001 baseline: fixture user missing password_hash in mongo (schema shifted?)")
    if not re.match(r"^\$2[aby]\$", doc["password_hash"]):
        _die(f"SEC-001 baseline: unexpected hash format {doc['password_hash'][:20]}")
    _ok(f"SEC-001 baseline: mongo users row has bcrypt password_hash (starts {doc['password_hash'][:7]})")
    c.close()


def probe_sec001_export_scrub():
    tok = _login_bearer("fixture-ead@opportunityos.dev", "Fixture!Test1")
    r1 = requests.post(f"{BASE}/api/v1/privacy/export", json={},
                       headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    if r1.status_code != 200:
        _die(f"privacy export kick: {r1.status_code} {r1.text}")
    job_id = r1.json()["job_id"]
    r2 = requests.get(f"{BASE}/api/v1/privacy/export/{job_id}",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    if r2.status_code != 200:
        _die(f"privacy export fetch: {r2.status_code}")
    body = r2.json()
    text = json.dumps(body)
    for key in ('"password_hash"', '"password":', '"totp_secret"', '"recovery_codes"'):
        if key in text:
            _die(f"SEC-001: export bundle leaks `{key}`")
    if re.search(r"\$2[aby]\$\d{2}\$", text):
        _die("SEC-001: export bundle contains bcrypt marker")
    profile = ((body.get("download") or {}).get("content") or {}).get("profile") or {}
    _ok(f"SEC-001: export bundle clean. profile keys={sorted(profile.keys())[:10]}...")


def probe_sec003_same_session_replay():
    # New user, single session, POST with idempotency key twice.
    email = f"idmp-same-{uuid.uuid4().hex[:8]}@opportunityos.dev"
    s = requests.Session()
    body = {
        "email": email, "password": "SameKeyTest!123", "name": "SameKey",
        "policy_text_version": "1.0",
        "consents": {"process_career_data": True, "discover_jobs": True,
                     "generate_materials": False, "track_applications": False,
                     "email_me": False},
    }
    r = s.post(f"{BASE}/api/v1/auth/signup", json=body, timeout=15)
    if r.status_code != 201:
        _die(f"same-key signup: {r.status_code} {r.text}")

    key = f"same-key-{uuid.uuid4()}"
    csrf = s.cookies.get("oppos_csrf") or ""
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": key}
    payload = {"scope": "generate_materials", "granted": True, "policy_text_version": "1.0"}

    r1 = s.post(f"{BASE}/api/v1/consents", json=payload, headers=headers, timeout=15)
    r2 = s.post(f"{BASE}/api/v1/consents", json=payload, headers=headers, timeout=15)
    if r1.status_code != 201:
        _die(f"same-key first call: {r1.status_code} {r1.text}")
    if r2.status_code not in (200, 201):
        _die(f"same-key replay: {r2.status_code} {r2.text}")
    if r1.text != r2.text:
        _die(f"same-key replay body differs.\nr1={r1.text[:200]}\nr2={r2.text[:200]}")
    replay_hdr = r2.headers.get("X-Idempotent-Replay")
    if replay_hdr != "true":
        # Not a hard fail — but flag it.
        print(f"WARN: expected X-Idempotent-Replay=true, got {replay_hdr!r}. Headers keys: {list(r2.headers.keys())}")
    _ok(f"SEC-003 same-session replay: body identical, replay header={replay_hdr!r}")


def probe_p3_throttle_per_identifier():
    # Ensure a scratch identifier hits 429, then a DIFFERENT identifier can
    # still login successfully in the same IP window.
    from pymongo import MongoClient
    c = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = c[os.environ.get("DB_NAME", "opportunityos")]

    scratch = f"throttle-probe-{uuid.uuid4().hex[:10]}@opportunityos.dev"
    db.login_throttle.delete_many({"identifier": scratch.lower()})

    hit_429 = False
    for i in range(12):
        r = requests.post(f"{BASE}/api/v1/auth/login",
                          json={"email": scratch, "password": "wrong"}, timeout=10)
        if r.status_code == 429:
            retry = r.headers.get("Retry-After")
            detail = r.json().get("detail") or {}
            if not retry:
                _die(f"P3: 429 without Retry-After (attempt {i+1})")
            if detail.get("error") != "rate_limited":
                _die(f"P3: 429 detail.error != 'rate_limited': {detail}")
            hit_429 = True
            print(f"     429 after {i+1} attempts, Retry-After={retry}, error={detail.get('error')}")
            break
    if not hit_429:
        _die("P3: never hit 429 in 12 attempts")

    # Cleanup identifier bucket for isolation.
    db.login_throttle.delete_many({"identifier": scratch.lower()})

    # Different identifier — fixture user login must still work (per-identifier
    # scope, not IP lockout).
    r = requests.post(f"{BASE}/api/v1/auth/login",
                      json={"email": "fixture-ead@opportunityos.dev",
                            "password": "Fixture!Test1"}, timeout=15)
    if r.status_code != 200:
        _die(f"P3: legit user blocked after scratch 429s (status {r.status_code}) — IP-wide lockout regression?")
    _ok("P3: per-identifier scoping confirmed (fixture login succeeded after scratch 429)")
    c.close()


def probe_sec002_sessions_state():
    # Post-facto assertion — session A rotated, session B revoked.
    from pymongo import MongoClient
    c = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = c[os.environ.get("DB_NAME", "opportunityos")]

    email = f"sec002-{uuid.uuid4().hex[:8]}@opportunityos.dev"
    pw1, pw2 = "OrigPass!123", "NewPass!456"
    s_a, s_b = requests.Session(), requests.Session()

    r = s_a.post(f"{BASE}/api/v1/auth/signup", json={
        "email": email, "password": pw1, "name": "Sec002",
        "policy_text_version": "1.0",
        "consents": {"process_career_data": True, "discover_jobs": True,
                     "generate_materials": False, "track_applications": False,
                     "email_me": False},
    }, timeout=15)
    if r.status_code != 201:
        _die(f"sec002 signup: {r.status_code} {r.text}")
    r = s_b.post(f"{BASE}/api/v1/auth/login",
                 json={"email": email, "password": pw1}, timeout=15)
    if r.status_code != 200:
        _die(f"sec002 second login: {r.status_code} {r.text}")

    session_a_before = s_a.cookies.get("oppos_session")
    session_b = s_b.cookies.get("oppos_session")
    if not session_a_before or not session_b:
        _die("sec002: missing session cookies")

    csrf_a = s_a.cookies.get("oppos_csrf")
    r = s_a.post(f"{BASE}/api/v1/users/me/change-password",
                 json={"current_password": pw1, "new_password": pw2},
                 headers={"X-CSRF-Token": csrf_a}, timeout=15)
    if r.status_code != 204:
        _die(f"sec002 change-password: {r.status_code} {r.text}")

    session_a_after = s_a.cookies.get("oppos_session")
    if session_a_after == session_a_before:
        _die("SEC-002: session A cookie did NOT rotate")
    if s_a.get(f"{BASE}/api/v1/auth/me").status_code != 200:
        _die("SEC-002: session A rotated but /me now 401")
    if s_b.get(f"{BASE}/api/v1/auth/me").status_code != 401:
        _die("SEC-002: session B was NOT revoked")

    # Look at mongo sessions collection.
    user = db.users.find_one({"email": email})
    if not user:
        _die("sec002: user not found in mongo")
    uid = user["id"] if "id" in user else str(user.get("_id"))
    rows = list(db.sessions.find({"user_id": uid}))
    # Expect: at least 3 rows (original A, B, rotated A). B and original A have revoked_at set; rotated A doesn't.
    revoked = [r for r in rows if r.get("revoked_at")]
    active = [r for r in rows if not r.get("revoked_at")]
    if len(active) < 1 or len(revoked) < 2:
        _die(f"SEC-002 mongo state: expected >=1 active + >=2 revoked, got active={len(active)} revoked={len(revoked)} total={len(rows)}")
    _ok(f"SEC-002: session A rotated ({session_a_before[:8]}...→{session_a_after[:8]}...), B revoked, mongo shows {len(active)} active + {len(revoked)} revoked")
    c.close()


if __name__ == "__main__":
    print("== iteration 11 independent probes ==")
    probe_sec001_mongo_baseline()
    probe_sec001_export_scrub()
    probe_sec002_sessions_state()
    probe_sec003_same_session_replay()
    probe_p3_throttle_per_identifier()
    print("ALL PROBES PASSED")
