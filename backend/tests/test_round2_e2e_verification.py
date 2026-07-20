"""End-to-end verification of Founder Fix Round-2 against the live preview.
Runs the exact scenarios listed in the review request, in order:
  1. Rebase auth semantics + secret never leaks.
  2. Rebase genuinely wipes state (pollute -> rebase -> assert clean).
  3. Gate-engine parity: clean baseline and post-mutation.
  4. reason_codes carry weight_ideal; sum == 100.
  5. Feedback round-trip: null -> helpful:true -> flip to helpful:false.
  6. User Zero read-only spot check remains pristine.
"""
from __future__ import annotations
import os
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://lynk-preview-2.preview.emergentagent.com").rstrip("/")
FIXTURE = {"email": "fixture-ead@opportunityos.dev", "password": "Fixture!Test1"}
USER_ZERO = {"email": "ujjwal@opportunityos.dev", "password": "Passport!Test0"}


def _read_service_token() -> str:
    with open("/app/backend/.env") as fh:
        for line in fh:
            if line.startswith("INTERNAL_SERVICE_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


TOKEN = _read_service_token()


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/api/v1/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _rebase():
    r = requests.post(f"{BASE}/api/internal/fixture/rebase",
                      headers={"X-Service-Token": TOKEN}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body.get("fixture_user_id")
    # Never echo the secret back
    assert TOKEN not in r.text
    return body["fixture_user_id"]


# ============================================================================
# P0 FIX #1 — rebase auth semantics + no-leak
# ============================================================================
def test_p0_1_rebase_auth_semantics():
    # (a) 401 missing token
    r = requests.post(f"{BASE}/api/internal/fixture/rebase", timeout=15)
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "service_token_missing"

    # (b) 403 wrong token
    r = requests.post(f"{BASE}/api/internal/fixture/rebase",
                      headers={"X-Service-Token": "not-the-real-thing"}, timeout=15)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "service_token_invalid"

    # (c) 200 correct token + fixture_user_id + note + no leak
    fx_id = _rebase()
    assert fx_id  # uuid

    # (e) semantic: source has 503 branch for not-configured token
    src = open("/app/backend/domains/fixtures/internal_router.py").read()
    assert "503" in src and "internal_service_token_not_configured" in src


# ============================================================================
# P0 FIX #1 — rebase actually wipes state
# ============================================================================
def test_p0_1_rebase_wipes_state():
    _rebase()
    tok = _login(**FIXTURE)
    H = {"Authorization": f"Bearer {tok}"}
    feed = requests.get(f"{BASE}/api/v1/jobs/feed", headers=H, timeout=30).json()
    passing_ids = [j["id"] for j in feed["passing"]]
    assert len(passing_ids) == 9

    # Pollute: shortlist one passing, hide a different one
    k = uuid.uuid4().hex[:8]
    r1 = requests.post(f"{BASE}/api/v1/jobs/{passing_ids[0]}/shortlist",
                       headers={**H, "Idempotency-Key": f"pol-sh-{k}"}, timeout=15)
    assert r1.status_code == 201
    r2 = requests.post(f"{BASE}/api/v1/jobs/{passing_ids[1]}/hide",
                       headers={**H, "Content-Type": "application/json",
                                "Idempotency-Key": f"pol-hd-{k}"},
                       json={"reason": "e2e pollution"}, timeout=15)
    assert r2.status_code == 201

    apps = requests.get(f"{BASE}/api/v1/applications", headers=H, timeout=15).json()
    apps_list = apps["applications"] if isinstance(apps, dict) else apps
    assert len(apps_list) == 1, f"expected 1 application after shortlist, got {apps}"
    feed_polluted = requests.get(f"{BASE}/api/v1/jobs/feed", headers=H, timeout=15).json()
    assert feed_polluted["totals"]["hidden"] == 1

    # Rebase
    _rebase()

    # Re-login (rebase wipes consents; test_credentials note says consents re-granted so
    # login should still succeed against the fixture user)
    tok2 = _login(**FIXTURE)
    H2 = {"Authorization": f"Bearer {tok2}"}
    apps2 = requests.get(f"{BASE}/api/v1/applications", headers=H2, timeout=15).json()
    apps2_list = apps2["applications"] if isinstance(apps2, dict) else apps2
    assert apps2_list == [], f"expected empty applications after rebase, got {apps2}"

    feed2 = requests.get(f"{BASE}/api/v1/jobs/feed", headers=H2, timeout=30).json()
    t = feed2["totals"]
    assert t["passing"] == 9
    assert t["excluded"] == 6
    assert t["hidden"] == 0
    assert t["excluded_by_reason"] == {"no_sponsorship_offered": 4, "requires_us_person": 2}


# ============================================================================
# P0 FIX #2 — clean baseline parity
# ============================================================================
def test_p0_2_parity_clean_baseline():
    _rebase()
    tok = _login(**FIXTURE)
    H = {"Authorization": f"Bearer {tok}"}
    f = requests.get(f"{BASE}/api/v1/jobs/feed", headers=H, timeout=30).json()["totals"]
    c = requests.get(f"{BASE}/api/v1/eligibility/coverage-preview", headers=H, timeout=30).json()["totals"]
    for k in ("passing", "excluded", "hidden", "excluded_by_reason", "unknown_by_reason"):
        assert f.get(k) == c.get(k), f"parity diff on {k}: feed={f.get(k)} cov={c.get(k)}"


# ============================================================================
# P0 FIX #2 — parity after mutations
# ============================================================================
def test_p0_2_parity_after_mutations():
    _rebase()
    tok = _login(**FIXTURE)
    H = {"Authorization": f"Bearer {tok}"}
    feed = requests.get(f"{BASE}/api/v1/jobs/feed", headers=H, timeout=30).json()
    passing = feed["passing"]
    assert len(passing) >= 2

    k = uuid.uuid4().hex[:8]
    r1 = requests.post(f"{BASE}/api/v1/jobs/{passing[0]['id']}/shortlist",
                       headers={**H, "Idempotency-Key": f"e2e-sh-{k}"}, timeout=15)
    assert r1.status_code == 201, r1.text
    r2 = requests.post(f"{BASE}/api/v1/jobs/{passing[1]['id']}/hide",
                       headers={**H, "Content-Type": "application/json",
                                "Idempotency-Key": f"e2e-hd-{k}"},
                       json={"reason": "e2e parity"}, timeout=15)
    assert r2.status_code == 201, r2.text

    f = requests.get(f"{BASE}/api/v1/jobs/feed", headers=H, timeout=30).json()["totals"]
    c = requests.get(f"{BASE}/api/v1/eligibility/coverage-preview", headers=H, timeout=30).json()["totals"]
    for key in ("passing", "excluded", "hidden", "excluded_by_reason", "unknown_by_reason"):
        assert f.get(key) == c.get(key), f"post-mutation parity diff on {key}: feed={f.get(key)} cov={c.get(key)}"
    assert f["hidden"] == 1
    assert f["passing"] == 7
    assert f["excluded"] == 7
    assert f["excluded_by_reason"].get("duplicate_application") == 1


# ============================================================================
# P0 FIX #3 — reason_codes carry weight_ideal; sum(weight_ideal) == 100
# ============================================================================
def test_p0_3_weight_ideal_sum_100():
    _rebase()
    tok = _login(**FIXTURE)
    H = {"Authorization": f"Bearer {tok}"}
    feed = requests.get(f"{BASE}/api/v1/jobs/feed", headers=H, timeout=30).json()
    jid = feed["passing"][0]["id"]
    m = requests.get(f"{BASE}/api/v1/matches/for-job/{jid}", headers=H, timeout=15).json()
    codes = m["reason_codes"]
    assert codes and len(codes) == 9, f"expected 9 reason_codes, got {len(codes)}"
    for rc in codes:
        for field in ("factor", "value", "direction", "weight_applied", "weight_ideal", "detail"):
            assert field in rc, f"reason_code missing field {field}: {rc}"
    total = sum(rc["weight_ideal"] for rc in codes)
    assert total == 100, f"sum(weight_ideal)={total}, expected 100"


# ============================================================================
# P1 FIX #4 — feedback round-trip visible on GET
# ============================================================================
def test_p1_4_feedback_round_trip():
    _rebase()
    tok = _login(**FIXTURE)
    H = {"Authorization": f"Bearer {tok}"}
    feed = requests.get(f"{BASE}/api/v1/jobs/feed", headers=H, timeout=30).json()
    jid = feed["passing"][0]["id"]

    m1 = requests.get(f"{BASE}/api/v1/matches/for-job/{jid}", headers=H, timeout=15).json()
    assert m1.get("feedback") is None

    k = uuid.uuid4().hex[:8]
    r = requests.post(f"{BASE}/api/v1/matches/for-job/{jid}/feedback",
                     headers={**H, "Content-Type": "application/json",
                              "Idempotency-Key": f"e2e-fbk-{k}"},
                     json={"helpful": True, "note": "clear"}, timeout=15)
    assert r.status_code == 201, r.text
    m2 = requests.get(f"{BASE}/api/v1/matches/for-job/{jid}", headers=H, timeout=15).json()
    assert m2["feedback"] is not None
    assert m2["feedback"]["helpful"] is True
    assert m2["feedback"].get("note") == "clear"
    assert "ts" in m2["feedback"] and "id" in m2["feedback"]

    # Flip with a NEW Idempotency-Key
    r2 = requests.post(f"{BASE}/api/v1/matches/for-job/{jid}/feedback",
                       headers={**H, "Content-Type": "application/json",
                                "Idempotency-Key": f"e2e-fbk-{k}-flip"},
                       json={"helpful": False}, timeout=15)
    assert r2.status_code == 201, r2.text
    m3 = requests.get(f"{BASE}/api/v1/matches/for-job/{jid}", headers=H, timeout=15).json()
    assert m3["feedback"]["helpful"] is False


# ============================================================================
# User Zero regression: read-only spot check remains pristine
# ============================================================================
def test_user_zero_stays_pristine():
    tok = _login(**USER_ZERO)
    H = {"Authorization": f"Bearer {tok}"}
    prefs = requests.get(f"{BASE}/api/v1/preferences/me", headers=H, timeout=15).json()
    assert prefs.get("version") == 0 and prefs.get("payload") is None, prefs
    elig = requests.get(f"{BASE}/api/v1/eligibility/me", headers=H, timeout=15).json()
    assert elig.get("version") == 0 and elig.get("status") == "unspecified", elig
    apps = requests.get(f"{BASE}/api/v1/applications", headers=H, timeout=15).json()
    apps_list = apps["applications"] if isinstance(apps, dict) else apps
    assert apps_list == [], apps
