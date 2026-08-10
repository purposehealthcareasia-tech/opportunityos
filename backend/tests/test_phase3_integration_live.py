"""Phase 3 Founder Brief — end-to-end integration tests against live preview.

Covers:
  * jobs/feed shape + lane filters + sort=velocity/nearest + degree-blind invariant
  * jobs/{id} gates+notes+route
  * shortlist 30-day per-employer cap → 429 employer_cap_reached
  * dashboard/supply-reality shape
  * credentials/catalog + credentials/{id} 404
  * walkins POST/GET + rate-limit
  * personas POST/GET/PATCH + claim_ids_not_approved_or_missing
"""
from __future__ import annotations
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://lynk-preview-2.preview.emergentagent.com").rstrip("/")
EMAIL = "fixture-ead@opportunityos.dev"
PASSWORD = "Fixture!Test1"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    # rebase fixture user first
    try:
        with open("/app/backend/.env") as f:
            for ln in f:
                if ln.startswith("INTERNAL_SERVICE_TOKEN="):
                    tok = ln.strip().split("=", 1)[1]
                    requests.post(f"{BASE_URL}/api/internal/fixture/rebase",
                                  headers={"X-Service-Token": tok}, timeout=30)
                    break
    except Exception:
        pass
    # login
    r = s.post(f"{BASE_URL}/api/v1/auth/login",
               json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    tok = body.get("access_token")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    # CSRF for mutating calls
    csrf = s.cookies.get("oppos_csrf")
    if csrf:
        s.headers["X-CSRF-Token"] = csrf
    return s


# ---------- jobs/feed ----------
class TestFeed:
    def test_feed_shape_and_degree_blind(self, client):
        r = client.get(f"{BASE_URL}/api/v1/jobs/feed", timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        for k in ("passing", "excluded", "totals", "weights_version", "lane", "sort", "within_mi"):
            assert k in b, f"missing key {k}"
        t = b["totals"]
        for k in ("live_jobs", "passing", "excluded", "hidden", "excluded_by_reason", "unknown_by_reason"):
            assert k in t
        ebr = t["excluded_by_reason"] or {}
        ubr = t["unknown_by_reason"] or {}
        # Degree-blind invariants
        assert "education_below_requirement" not in ebr
        assert "experience_below_band" not in ebr
        assert "education_unknown" not in ubr
        assert "experience_missing" not in ubr

    def test_feed_lane_income_now(self, client):
        r = client.get(f"{BASE_URL}/api/v1/jobs/feed?lane=income_now", timeout=30)
        assert r.status_code == 200
        b = r.json()
        assert b["lane"] == "income_now"
        for row in b["passing"]:
            lane = row.get("lane") or row.get("lane_hint")
            if lane is not None:
                assert lane == "income_now", f"lane leak: {lane}"

    def test_feed_lane_career(self, client):
        r = client.get(f"{BASE_URL}/api/v1/jobs/feed?lane=career", timeout=30)
        assert r.status_code == 200
        b = r.json()
        assert b["lane"] == "career"

    def test_feed_sort_velocity(self, client):
        r = client.get(f"{BASE_URL}/api/v1/jobs/feed?sort=velocity", timeout=30)
        assert r.status_code == 200
        b = r.json()
        assert b["sort"] == "velocity"
        # cards include velocity object
        if b["passing"]:
            for row in b["passing"][:5]:
                assert "velocity" in row, f"missing velocity chip in {list(row.keys())}"
                v = row["velocity"]
                for k in ("hourly_rate_usd", "weekly_est_usd", "velocity_score"):
                    assert k in v
        # sort DESC by velocity_score
        scores = [r.get("velocity", {}).get("velocity_score") for r in b["passing"]]
        non_null = [s for s in scores if s is not None]
        if len(non_null) >= 2:
            assert non_null == sorted(non_null, reverse=True), f"not DESC: {non_null}"

    def test_feed_sort_nearest(self, client):
        r = client.get(f"{BASE_URL}/api/v1/jobs/feed?sort=nearest", timeout=30)
        assert r.status_code == 200
        b = r.json()
        assert b["sort"] == "nearest"
        dists = [r.get("distance_from_phoenix_mi") for r in b["passing"]]
        non_null = [d for d in dists if isinstance(d, (int, float))]
        if len(non_null) >= 2:
            assert non_null == sorted(non_null), f"not ASC: {non_null[:6]}"


# ---------- jobs/{id} ----------
class TestJobDetail:
    def test_job_detail_shape_and_gates(self, client):
        r = client.get(f"{BASE_URL}/api/v1/jobs/feed", timeout=30)
        assert r.status_code == 200
        b = r.json()
        # prefer a SampleCo passing job to be deterministic
        rows = [x for x in b["passing"] if "sampleco" in (x.get("company_name") or "").lower()] or b["passing"]
        assert rows, "no passing job"
        jid = rows[0]["id"]
        r2 = client.get(f"{BASE_URL}/api/v1/jobs/{jid}", timeout=30)
        assert r2.status_code == 200, r2.text
        d = r2.json()
        for k in ("gates", "pass_all", "notes", "have_gap", "route"):
            assert k in d, f"missing {k}"
        expected = [
            "vacancy_open", "authorization_scope", "duplicate_check", "work_auth",
            "sponsorship", "stem_opt_viability", "itar", "security_clearance",
            "licensure", "location_onsite", "experience_band", "education_requirement",
            "salary_floor", "employer_exclusions",
        ]
        names = [g["name"] for g in d["gates"]]
        assert names == expected, f"gate order wrong: {names}"
        assert isinstance(d["notes"], list)


# ---------- shortlist employer cap ----------
class TestEmployerCap:
    def test_shortlist_3_sampleco_then_4th_429(self, client):
        """Assisted-lane fixture pre-consumes 1 SampleCo slot of the
        30-day employer cap (see FIXTURE_EAD_SAMPLECO_APPS_PRE_CONSUMED).
        So the FIRST fresh shortlist that hits 429 is index
        EMPLOYER_CAP_FIRST_429_SAMPLECO_INDEX (2 when cap=3 and 1 slot
        pre-consumed). Derived from the seeder + service constants."""
        from tests._fixture_expectations import (
            EMPLOYER_CAP_MAX_PER_30_DAYS,
            EMPLOYER_CAP_FIRST_429_SAMPLECO_INDEX,
        )
        r = client.get(f"{BASE_URL}/api/v1/jobs/feed", timeout=30)
        assert r.status_code == 200
        b = r.json()
        sampleco_ids = [x["id"] for x in b["passing"]
                        if "sampleco" in (x.get("company_name") or "").lower()]
        need = EMPLOYER_CAP_FIRST_429_SAMPLECO_INDEX + 1
        if len(sampleco_ids) < need:
            pytest.skip(f"Only {len(sampleco_ids)} passing SampleCo jobs; need {need}")
        codes = []
        for jid in sampleco_ids[:need]:
            rr = client.post(f"{BASE_URL}/api/v1/jobs/{jid}/shortlist", json={}, timeout=30)
            codes.append((jid, rr.status_code, rr.text if rr.status_code != 200 else ""))
        # Indices [0..first_429-1] should succeed, [first_429] should 429.
        for i in range(EMPLOYER_CAP_FIRST_429_SAMPLECO_INDEX):
            assert codes[i][1] in (200, 201), (i, codes)
        i429 = EMPLOYER_CAP_FIRST_429_SAMPLECO_INDEX
        assert codes[i429][1] == 429, f"expected 429 at index {i429}, got {codes[i429]}"
        import json as _json
        body = _json.loads(codes[i429][2]) if codes[i429][2] else {}
        det = body.get("detail") or body
        assert det.get("error") == "employer_cap_reached", det
        assert det.get("cap") == EMPLOYER_CAP_MAX_PER_30_DAYS, det
        assert det.get("window_days") == 30, det


# ---------- dashboard/supply-reality ----------
def test_supply_reality(client):
    r = client.get(f"{BASE_URL}/api/v1/dashboard/supply-reality", timeout=30)
    assert r.status_code == 200, r.text
    b = r.json()
    for k in ("supply", "budget", "employer_cap", "backlog"):
        assert k in b
    s = b["supply"]
    for k in ("live_jobs", "live_by_lane", "new_today", "within_25mi_of_phoenix", "within_60mi_of_phoenix"):
        assert k in s, f"missing supply.{k}"
    for k in ("career", "income_now"):
        assert k in s["live_by_lane"]
    for k in ("plan", "plan_label", "daily_submit_cap", "submitted_today", "budget_remaining_today"):
        assert k in b["budget"], f"missing budget.{k}"
    ec = b["employer_cap"]
    assert ec.get("cap") == 3
    assert ec.get("window_days") == 30
    assert "top_employers_last_30d" in ec
    assert "open_applications" in b["backlog"]


# ---------- credentials ----------
class TestCredentials:
    def test_catalog(self, client):
        r = client.get(f"{BASE_URL}/api/v1/credentials/catalog", timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        assert "credentials" in b
        assert b.get("total", len(b["credentials"])) >= 9
        for row in b["credentials"]:
            for k in ("id", "label", "kind", "mandatory", "typical_hourly",
                      "time_to_credential", "approx_cost_usd", "suggested_next", "notes"):
                assert k in row, f"missing {k} in {row.get('id')}"

    def test_by_id_cdl(self, client):
        r = client.get(f"{BASE_URL}/api/v1/credentials/cdl-class-a", timeout=30)
        assert r.status_code == 200
        assert r.json()["id"] == "cdl-class-a"

    def test_by_id_404(self, client):
        r = client.get(f"{BASE_URL}/api/v1/credentials/does-not-exist", timeout=30)
        assert r.status_code == 404
        b = r.json()
        det = b.get("detail") or b
        val = det if isinstance(det, str) else (det.get("error") or det.get("message") or "")
        assert "credential_not_found" in str(val) or "not_found" in str(val).lower(), b


# ---------- walkins ----------
class TestWalkins:
    def test_create_and_list(self, client):
        stamp = uuid.uuid4().hex[:8]
        payload = {"employer": f"TEST_Walkin_{stamp}", "location": "Phoenix, AZ",
                   "outcome": "submitted", "notes": "integration test"}
        r = client.post(f"{BASE_URL}/api/v1/walkins", json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text
        r2 = client.get(f"{BASE_URL}/api/v1/walkins/mine", timeout=30)
        assert r2.status_code == 200, r2.text
        items = r2.json()
        items = items.get("walkins") if isinstance(items, dict) else items
        assert any(f"TEST_Walkin_{stamp}" in (w.get("employer") or "") for w in items)

    def test_rate_limit_6th_returns_429(self, client):
        codes = []
        for i in range(6):
            r = client.post(f"{BASE_URL}/api/v1/walkins",
                            json={"employer": f"TEST_RL_{uuid.uuid4().hex[:6]}",
                                  "location": "Phoenix, AZ", "outcome": "got_application"},
                            timeout=30)
            codes.append(r.status_code)
            if r.status_code == 429:
                b = r.json()
                det = b.get("detail") or b
                val = det if isinstance(det, str) else (det.get("error") or "")
                assert "walkin_rate_limited" in str(val), det
                return
        assert 429 in codes, f"expected 429 in {codes}"


# ---------- personas ----------
class TestPersonas:
    def test_create_list_patch_and_bad_claim(self, client):
        payload = {"label": f"TEST Persona {uuid.uuid4().hex[:6]}",
                   "intent": "career",
                   "priority_claim_ids": []}
        r = client.post(f"{BASE_URL}/api/v1/personas", json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text
        pid = r.json().get("id") or r.json().get("persona", {}).get("id")
        assert pid, r.text
        r2 = client.get(f"{BASE_URL}/api/v1/personas", timeout=30)
        assert r2.status_code == 200
        items = r2.json()
        items = items.get("personas") if isinstance(items, dict) else items
        assert any(p.get("id") == pid for p in items)
        # PATCH → v+1
        r3 = client.patch(f"{BASE_URL}/api/v1/personas/{pid}",
                          json={"label": "TEST Persona updated"}, timeout=30)
        assert r3.status_code in (200, 201), r3.text
        # Bad claim id
        r4 = client.post(f"{BASE_URL}/api/v1/personas",
                         json={"label": "TEST Bad", "intent": "career",
                               "priority_claim_ids": ["nonexistent-claim-id"]},
                         timeout=30)
        assert r4.status_code == 400, r4.text
        det = r4.json().get("detail") or r4.json()
        val = det if isinstance(det, str) else (det.get("error") or "")
        assert "claim_ids_not_approved_or_missing" in str(val), det
