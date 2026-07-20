"""Founder Fix Round-2 tests: parity between /jobs/feed and /eligibility/coverage-preview,
plus /api/internal/fixture/rebase auth semantics.
"""
from __future__ import annotations
import os
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://lynk-preview-2.preview.emergentagent.com").rstrip("/")
FIXTURE = {"email": "fixture-ead@opportunityos.dev", "password": "Fixture!Test1"}


def _read_service_token() -> str:
    tok = ""
    with open("/app/backend/.env") as fh:
        for line in fh:
            if line.startswith("INTERNAL_SERVICE_TOKEN="):
                tok = line.split("=", 1)[1].strip()
                break
    return tok


SERVICE_TOKEN = _read_service_token()


def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/api/v1/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _rebase_fixture() -> None:
    r = requests.post(
        f"{BASE}/api/internal/fixture/rebase",
        headers={"X-Service-Token": SERVICE_TOKEN},
        timeout=30,
    )
    assert r.status_code == 200, r.text


@pytest.fixture
def fixture_token() -> str:
    _rebase_fixture()
    return _login(FIXTURE["email"], FIXTURE["password"])


# -------- P0 #1: fixture rebase endpoint auth semantics --------

def test_rebase_missing_token_401():
    r = requests.post(f"{BASE}/api/internal/fixture/rebase", timeout=15)
    assert r.status_code == 401
    body = r.json()
    assert body["detail"]["error"] == "service_token_missing"


def test_rebase_wrong_token_403():
    r = requests.post(
        f"{BASE}/api/internal/fixture/rebase",
        headers={"X-Service-Token": "definitely-not-the-real-token"},
        timeout=15,
    )
    assert r.status_code == 403
    body = r.json()
    assert body["detail"]["error"] == "service_token_invalid"


def test_rebase_correct_token_200_and_never_echoes_secret():
    assert SERVICE_TOKEN, "INTERNAL_SERVICE_TOKEN must be set for this test"
    r = requests.post(
        f"{BASE}/api/internal/fixture/rebase",
        headers={"X-Service-Token": SERVICE_TOKEN},
        timeout=30,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body.get("fixture_user_id")
    # Token must never appear in the response body (defense-in-depth check).
    assert SERVICE_TOKEN not in r.text


# -------- P0 #2: gate-engine parity between feed and coverage-preview --------

def _fetch_totals(token: str) -> tuple[dict, dict]:
    headers = {"Authorization": f"Bearer {token}"}
    f = requests.get(f"{BASE}/api/v1/jobs/feed", headers=headers, timeout=30).json()
    c = requests.get(f"{BASE}/api/v1/eligibility/coverage-preview", headers=headers, timeout=30).json()
    return f["totals"], c["totals"]


def test_parity_clean_baseline(fixture_token):
    ft, ct = _fetch_totals(fixture_token)
    for k in ("passing", "excluded", "hidden", "excluded_by_reason", "unknown_by_reason"):
        assert ft.get(k) == ct.get(k), f"feed[{k}]={ft.get(k)} vs cov[{k}]={ct.get(k)}"
    # Also assert acceptance-check-B geometry
    assert ft["passing"] == 9
    assert ft["excluded"] == 6
    assert ft["hidden"] == 0
    assert ft["excluded_by_reason"] == {"no_sponsorship_offered": 4, "requires_us_person": 2}


def test_parity_after_mutations(fixture_token):
    headers = {"Authorization": f"Bearer {fixture_token}"}
    feed = requests.get(f"{BASE}/api/v1/jobs/feed", headers=headers, timeout=30).json()
    passing = feed["passing"]
    assert len(passing) >= 2
    key = uuid.uuid4().hex[:8]
    # shortlist one
    r1 = requests.post(f"{BASE}/api/v1/jobs/{passing[0]['id']}/shortlist",
                       headers={**headers, "Idempotency-Key": f"parity-sh-{key}"}, timeout=15)
    assert r1.status_code == 201, r1.text
    # hide another
    r2 = requests.post(f"{BASE}/api/v1/jobs/{passing[1]['id']}/hide",
                       headers={**headers, "Content-Type": "application/json",
                                "Idempotency-Key": f"parity-hd-{key}"},
                       json={"reason": "parity_test"}, timeout=15)
    assert r2.status_code == 201, r2.text
    # parity must hold
    ft, ct = _fetch_totals(fixture_token)
    for k in ("passing", "excluded", "hidden", "excluded_by_reason", "unknown_by_reason"):
        assert ft.get(k) == ct.get(k), f"[after mutation] feed[{k}]={ft.get(k)} vs cov[{k}]={ct.get(k)}"
    # Duplicate-application should be reflected in both.
    assert ft["excluded_by_reason"].get("duplicate_application") == 1
    assert ft["hidden"] == 1
    assert ft["passing"] == 7


# -------- P1 #4: feedback round-trip --------

def test_feedback_round_trip_visible_on_get(fixture_token):
    headers = {"Authorization": f"Bearer {fixture_token}"}
    feed = requests.get(f"{BASE}/api/v1/jobs/feed", headers=headers, timeout=30).json()
    assert feed["passing"], "need at least one passing job to score"
    jid = feed["passing"][0]["id"]

    m1 = requests.get(f"{BASE}/api/v1/matches/for-job/{jid}", headers=headers, timeout=15).json()
    assert "feedback" in m1
    assert m1["feedback"] is None  # fresh rebase → no prior feedback

    # weight_ideal must be present so the UI counterfactual can compute score potential
    assert m1["reason_codes"], "expected reason_codes to be present"
    assert all("weight_ideal" in rc for rc in m1["reason_codes"]), \
        f"weight_ideal missing on some reason_codes: {[rc for rc in m1['reason_codes'] if 'weight_ideal' not in rc]}"

    key = uuid.uuid4().hex[:8]
    r = requests.post(f"{BASE}/api/v1/matches/for-job/{jid}/feedback",
                      headers={**headers, "Content-Type": "application/json",
                               "Idempotency-Key": f"fbk-{key}"},
                      json={"helpful": True, "note": "clear"}, timeout=15)
    assert r.status_code == 201, r.text

    m2 = requests.get(f"{BASE}/api/v1/matches/for-job/{jid}", headers=headers, timeout=15).json()
    assert m2["feedback"] is not None, "feedback should be surfaced on GET"
    assert m2["feedback"]["helpful"] is True
    assert m2["feedback"].get("note") == "clear"

    # Flip to unhelpful → the latest ts wins
    r2 = requests.post(f"{BASE}/api/v1/matches/for-job/{jid}/feedback",
                       headers={**headers, "Content-Type": "application/json",
                                "Idempotency-Key": f"fbk-{key}-b"},
                       json={"helpful": False}, timeout=15)
    assert r2.status_code == 201, r2.text
    m3 = requests.get(f"{BASE}/api/v1/matches/for-job/{jid}", headers=headers, timeout=15).json()
    assert m3["feedback"]["helpful"] is False, "GET should reflect the LATEST feedback"
