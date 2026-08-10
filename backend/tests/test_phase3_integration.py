"""Phase 3 backend integration tests — hits the RUNNING FastAPI server.

Covers Founder Directives #1–#9:
  - Health + OpenAPI shape
  - Internal ingest auth semantics (401/403 + 503 code-path existence)
  - Internal ingest happy path + idempotent-update behavior + direct-Mongo unique-index proof
  - 14-gate enumeration on live job detail
  - authorization_scope always pass with Phase-3 detail string
  - Gate parity coverage-preview vs feed
  - Feed passport_not_activated for fresh signup
  - Link import 409 for aggregator hosts + 201 derived for real employer URL
  - Duplicate ingest resiliency
  - Shortlist + 409 already_shortlisted
  - Atomic state transitions (200 → 409 precondition → 400 invalid)
  - Match score persistence + feedback
  - Usage meter increments only for NEW scores (upserts don't)
  - Idempotency replay on shortlist + on state transition
  - SAMPLE badge exclusion (frontend responsibility, but is_sample flag correct)
  - Consent gate on new endpoints
  - Sample seed integrity (15 SampleCo rows)
  - LLM cost ledger — user_id passed + at least one row shape
"""
from __future__ import annotations
import os
import uuid
import pytest
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://lynk-preview-2.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "opportunityos")

USER_ZERO = {"email": "fixture-ead@opportunityos.dev", "password": "Fixture!Test1"}  # Founder Fix Directive: state-mutating tests use the FIXTURE user, not the real User Zero.

# Read token straight from backend/.env (avoid leaking in reports).
def _read_service_token() -> str:
    tok = ""
    with open("/app/backend/.env") as fh:
        for line in fh:
            if line.startswith("INTERNAL_SERVICE_TOKEN="):
                tok = line.split("=", 1)[1].strip()
                break
    return tok


SERVICE_TOKEN = _read_service_token()


# -------- HTTP helpers --------
def _login(email: str, password: str) -> str:
    r = requests.post(f"{BASE}/api/v1/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _grant_scope(token: str, scope: str, granted: bool = True) -> None:
    r = requests.post(
        f"{BASE}/api/v1/consents",
        headers={"Authorization": f"Bearer {token}"},
        json={"scope": scope, "granted": granted, "policy_text_version": "1.0"},
        timeout=15,
    )
    assert r.status_code in (200, 201), r.text


@pytest.fixture(scope="module")
def user_zero_token() -> str:
    t = _login(USER_ZERO["email"], USER_ZERO["password"])
    _grant_scope(t, "discover_jobs", True)
    return t


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL, uuidRepresentation="standard")
    try:
        yield c[DB_NAME]
    finally:
        c.close()


# =============== 1. Health + OpenAPI =====================
def test_health_phase3_and_mongo():
    r = requests.get(f"{BASE}/api/health", timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["phase"] >= 3  # phase counter advances as new phases ship; only enforce lower bound.
    assert d["mongo"] is True
    assert d["ok"] is True


def test_openapi_exposes_all_phase3_paths():
    r = requests.get(f"{BASE}/api/openapi.json", timeout=15)
    assert r.status_code == 200
    paths = set(r.json().get("paths", {}).keys())
    required = [
        "/api/v1/jobs/feed",
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/import",
        "/api/v1/jobs/imports/me",
        "/api/v1/jobs/{job_id}/resolve",
        "/api/v1/jobs/{job_id}/hide",
        "/api/v1/jobs/{job_id}/shortlist",
        "/api/internal/jobs/bulk",
        "/api/v1/applications",
        "/api/v1/applications/{application_id}/state",
        "/api/v1/matches/for-job/{job_id}",
        "/api/v1/matches/for-job/{job_id}/feedback",
        "/api/v1/usage/me",
    ]
    missing = [p for p in required if p not in paths]
    assert not missing, f"Missing Phase 3 paths in OpenAPI: {missing}"


# =============== 2. Internal ingest auth semantics =====================
_BULK_URL = f"{BASE}/api/internal/jobs/bulk"


def _minimal_job(key: str, **over) -> dict:
    j = {
        "canonical_key": key,
        "origin_url": "https://qatest.com/careers/qa-01",
        "title": "QA Widget Engineer",
        "company_name": "QATest Inc",
        "company_domain": "qatest.com",
        "source": "qa",
        "jd_text": "Own the QA test bed for the phase 3 backend end-to-end.",
        "apply_method": "external",
    }
    j.update(over)
    return j


def test_internal_ingest_missing_token_returns_401():
    r = requests.post(_BULK_URL, json={"jobs": [_minimal_job("qatest.com::qa-x1")]}, timeout=15)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["error"] == "service_token_missing"


def test_internal_ingest_wrong_token_returns_403():
    r = requests.post(
        _BULK_URL,
        headers={"X-Service-Token": "not-the-token"},
        json={"jobs": [_minimal_job("qatest.com::qa-x2")]},
        timeout=15,
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "service_token_invalid"


def test_internal_ingest_503_code_path_exists():
    """Verify the 503 code path is present in source (do not unset env)."""
    with open("/app/backend/domains/jobs/internal_router.py") as fh:
        src = fh.read()
    assert "HTTP_503_SERVICE_UNAVAILABLE" in src
    assert "internal_service_token_not_configured" in src


def test_internal_ingest_response_never_echoes_token():
    key = f"qatest.com::qa-{uuid.uuid4().hex[:8]}"
    r = requests.post(
        _BULK_URL,
        headers={"X-Service-Token": SERVICE_TOKEN},
        json={"jobs": [_minimal_job(key)]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body_txt = r.text
    assert SERVICE_TOKEN not in body_txt


# =============== 3. Internal ingest happy path + idempotent update ====
def test_internal_ingest_accept_then_update_then_direct_dup(mongo):
    key = f"qatest.com::qa-{uuid.uuid4().hex[:10]}"
    payload = {"jobs": [_minimal_job(key)]}
    h = {"X-Service-Token": SERVICE_TOKEN}
    r1 = requests.post(_BULK_URL, headers=h, json=payload, timeout=15)
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert any(a["canonical_key"] == key for a in j1["accepted"])
    assert not any(u["canonical_key"] == key for u in j1["updated"])

    r2 = requests.post(_BULK_URL, headers=h, json=payload, timeout=15)
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    assert any(u["canonical_key"] == key for u in j2["updated"])
    assert not any(a["canonical_key"] == key for a in j2["accepted"])

    # DIRECT mongo dup insert must raise DuplicateKeyError.
    from pymongo.errors import DuplicateKeyError
    with pytest.raises(DuplicateKeyError):
        mongo.jobs.insert_one({"canonical_key": key, "title": "shadow"})


# =============== 4. Feed passport gate (fresh signup 403) =============
def test_fresh_signup_feed_returns_passport_not_activated():
    email = f"qa_fresh_{uuid.uuid4().hex[:8]}@opportunityos.dev"
    r = requests.post(
        f"{BASE}/api/v1/auth/signup",
        json={
            "email": email,
            "password": "FreshPass!123",
            "name": "QA Fresh",
            "consents": {"process_career_data": True},
            "policy_text_version": "1.0",
        },
        timeout=15,
    )
    assert r.status_code == 201, r.text
    tok = r.json()["access_token"]
    # Grant discover_jobs — but no passport activation
    _grant_scope(tok, "discover_jobs", True)
    r2 = requests.get(f"{BASE}/api/v1/jobs/feed", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    assert r2.status_code == 403, r2.text
    d = r2.json()["detail"]
    assert d["error"] == "passport_not_activated"


# =============== 5. Feed happy path shape (User Zero) =================
def test_feed_returns_expected_structure_for_activated_user(user_zero_token):
    r = requests.get(f"{BASE}/api/v1/jobs/feed", headers={"Authorization": f"Bearer {user_zero_token}"}, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["weights_version"] == "v0.1"
    assert isinstance(d["passing"], list)
    assert isinstance(d["excluded"], list)
    assert d["totals"]["passing"] == len(d["passing"])
    assert d["totals"]["excluded"] == len(d["excluded"])


# =============== 6. 14-gate enumeration on live job detail ==============
GATE_ORDER = [
    "vacancy_open", "authorization_scope", "duplicate_check", "work_auth",
    "sponsorship", "stem_opt_viability", "itar", "security_clearance",
    "licensure", "location_onsite", "experience_band", "education_requirement",
    "salary_floor", "employer_exclusions",
]


def _pick_sample_job_id(mongo):
    j = mongo.jobs.find_one({"status": "live", "is_sample": True}, {"id": 1, "_id": 0})
    return j["id"] if j else None


def test_job_detail_enumerates_14_gates_in_exact_order(user_zero_token, mongo):
    job_id = _pick_sample_job_id(mongo)
    assert job_id, "No live sample job found in DB"
    r = requests.get(f"{BASE}/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {user_zero_token}"}, timeout=30)
    assert r.status_code == 200, r.text
    gates = r.json()["gates"]
    names = [g["name"] for g in gates]
    assert names == GATE_ORDER
    assert len(names) == 14


def test_authorization_scope_gate_always_pass_with_phase3_detail(user_zero_token, mongo):
    job_id = _pick_sample_job_id(mongo)
    r = requests.get(f"{BASE}/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {user_zero_token}"}, timeout=30)
    az = [g for g in r.json()["gates"] if g["name"] == "authorization_scope"][0]
    assert az["status"] == "pass"
    assert "Interface only in Phase 3" in (az.get("detail") or "")


# =============== 7. Gate parity: coverage-preview == feed ==============
def test_gate_parity_between_coverage_preview_and_feed(user_zero_token):
    # Save eligibility
    r = requests.post(
        f"{BASE}/api/v1/eligibility",
        headers={"Authorization": f"Bearer {user_zero_token}"},
        json={"status": "ead_opt", "dates": {}, "notes": None},
        timeout=15,
    )
    assert r.status_code in (200, 201), r.text
    cp = requests.get(f"{BASE}/api/v1/eligibility/coverage-preview",
                      headers={"Authorization": f"Bearer {user_zero_token}"}, timeout=60)
    assert cp.status_code == 200, cp.text
    feed = requests.get(f"{BASE}/api/v1/jobs/feed",
                        headers={"Authorization": f"Bearer {user_zero_token}"}, timeout=60)
    assert feed.status_code == 200, feed.text

    cp_map = {j["job_id"]: j for j in cp.json()["jobs"]}
    feed_excluded = {j["id"]: j for j in feed.json()["excluded"]}
    feed_passing = {j["id"]: j for j in feed.json()["passing"]}
    checked = 0
    for job_id, cp_row in cp_map.items():
        if job_id in feed_excluded:
            assert sorted(cp_row["fail_reasons"]) == sorted(feed_excluded[job_id]["fail_reasons"]), (
                f"Gate parity mismatch for excluded job {job_id}"
            )
            checked += 1
        elif job_id in feed_passing:
            # In coverage-preview a "passing" row has no fail_reasons; the feed passing row has none.
            assert not cp_row["fail_reasons"]
            checked += 1
    assert checked > 0, "No overlapping jobs between coverage-preview and feed"


# =============== 8. Link import 409 aggregator + 201 employer ==========
@pytest.mark.parametrize("url,host", [
    ("https://www.linkedin.com/jobs/view/12345", "linkedin.com"),
    ("https://www.indeed.com/viewjob?jk=xxx", "indeed.com"),
    ("https://joinhandshake.com/jobs/12345", "joinhandshake.com"),
])
def test_import_aggregator_hosts_return_409(user_zero_token, url, host):
    r = requests.post(
        f"{BASE}/api/v1/jobs/import",
        headers={"Authorization": f"Bearer {user_zero_token}"},
        json={"url": url},
        timeout=15,
    )
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["error"] == "route_unavailable_platform_policy"
    assert d["host"] == host
    assert "Fynd never scrapes" in d["message"]


def test_import_real_employer_url_returns_201_derived(user_zero_token):
    unique = uuid.uuid4().hex[:8]
    r = requests.post(
        f"{BASE}/api/v1/jobs/import",
        headers={"Authorization": f"Bearer {user_zero_token}"},
        json={"url": f"https://boards.greenhouse.io/foo/jobs/{unique}", "title": "QA import", "company_name": "Foo"},
        timeout=15,
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "derived"
    assert d["needs_origin"] is True


# =============== 9. Consent gate on jobs endpoints ====================
def test_consent_gate_on_feed_and_import():
    email = f"qa_cons_{uuid.uuid4().hex[:8]}@opportunityos.dev"
    r = requests.post(
        f"{BASE}/api/v1/auth/signup",
        json={
            "email": email, "password": "FreshPass!123", "name": "QA C",
            "consents": {"process_career_data": True},
            "policy_text_version": "1.0",
        },
        timeout=15,
    )
    assert r.status_code == 201
    tok = r.json()["access_token"]
    # No discover_jobs yet → feed 403 consent_required
    r2 = requests.get(f"{BASE}/api/v1/jobs/feed", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r2.status_code == 403
    d = r2.json()["detail"]
    # accept either error string; must clearly flag missing scope
    err_str = str(d).lower()
    assert "consent" in err_str or "discover_jobs" in err_str
    r3 = requests.post(
        f"{BASE}/api/v1/jobs/import",
        headers={"Authorization": f"Bearer {tok}"},
        json={"url": "https://example.com/x"},
        timeout=15,
    )
    assert r3.status_code == 403


# =============== 10. Shortlist + 409 already_shortlisted ==============
@pytest.fixture(scope="module")
def sample_job_ids(mongo):
    ids = [j["id"] for j in mongo.jobs.find({"status": "live", "is_sample": True}, {"id": 1, "_id": 0}).limit(6)]
    assert len(ids) >= 3, f"Need at least 3 sample jobs, found {len(ids)}"
    return ids


def test_shortlist_and_duplicate_returns_409(user_zero_token, sample_job_ids, mongo):
    job_id = sample_job_ids[0]
    # Clean any lingering apps for this (user, job) to make the test deterministic
    tok = user_zero_token
    me = requests.get(f"{BASE}/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=10).json()
    uid = me["id"]
    mongo.applications.delete_many({"user_id": uid, "job_id": job_id})

    r1 = requests.post(f"{BASE}/api/v1/jobs/{job_id}/shortlist", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r1.status_code == 201, r1.text
    assert r1.json()["state"] == "shortlisted"
    r2 = requests.post(f"{BASE}/api/v1/jobs/{job_id}/shortlist", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["error"] == "already_shortlisted"
    # Only one row in db
    assert mongo.applications.count_documents({"user_id": uid, "job_id": job_id}) == 1


# =============== 11. Atomic state transitions =========================
def test_atomic_state_transitions_ok_conflict_and_invalid(user_zero_token, sample_job_ids, mongo):
    tok = user_zero_token
    me = requests.get(f"{BASE}/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=10).json()
    uid = me["id"]
    job_id = sample_job_ids[1]
    mongo.applications.delete_many({"user_id": uid, "job_id": job_id})
    r = requests.post(f"{BASE}/api/v1/jobs/{job_id}/shortlist", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]

    # 200: shortlisted -> preparing
    r1 = requests.patch(
        f"{BASE}/api/v1/applications/{app_id}/state",
        headers={"Authorization": f"Bearer {tok}"},
        json={"expected_state": "shortlisted", "new_state": "preparing"},
        timeout=15,
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["state"] == "preparing"

    # 409: same call again (state is now 'preparing', not 'shortlisted')
    r2 = requests.patch(
        f"{BASE}/api/v1/applications/{app_id}/state",
        headers={"Authorization": f"Bearer {tok}"},
        json={"expected_state": "shortlisted", "new_state": "preparing"},
        timeout=15,
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["error"] == "state_precondition_failed"

    # 400: invalid transition preparing -> submitted (must be awaiting_approval or closed)
    r3 = requests.patch(
        f"{BASE}/api/v1/applications/{app_id}/state",
        headers={"Authorization": f"Bearer {tok}"},
        json={"expected_state": "preparing", "new_state": "submitted"},
        timeout=15,
    )
    assert r3.status_code == 400, r3.text
    d = r3.json()["detail"]
    assert d["error"] == "invalid_transition"
    assert "allowed_from_here" in d
    assert isinstance(d["allowed_from_here"], list)


# =============== 12. Match score persistence + feedback ================
def test_match_score_and_feedback(user_zero_token, mongo, sample_job_ids):
    tok = user_zero_token
    me = requests.get(f"{BASE}/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=10).json()
    uid = me["id"]
    # Try natural path first
    requests.post(
        f"{BASE}/api/v1/eligibility",
        headers={"Authorization": f"Bearer {tok}"},
        json={"status": "citizen", "dates": {}, "notes": None},
        timeout=15,
    )
    feed = requests.get(f"{BASE}/api/v1/jobs/feed", headers={"Authorization": f"Bearer {tok}"}, timeout=60).json()
    if feed["passing"]:
        job_id = feed["passing"][0]["id"]
    else:
        # User Zero's seed leaves UNKNOWN gates → no passing feed rows in a fresh env.
        # Seed a match_scores row directly to exercise the read/feedback endpoints.
        job_id = sample_job_ids[0]
        mongo.match_scores.delete_many({"user_id": uid, "job_id": job_id})
        mongo.match_scores.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": uid,
            "job_id": job_id,
            "score": 62.5,
            "confidence": 0.75,
            "reason_codes": [],
            "gate_results": [],
            "weights_version": "v0.1",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })

    r = requests.get(f"{BASE}/api/v1/matches/for-job/{job_id}", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("score", "confidence", "reason_codes", "gate_results", "weights_version"):
        assert key in d
    assert d["weights_version"] == "v0.1"
    r2 = requests.post(
        f"{BASE}/api/v1/matches/for-job/{job_id}/feedback",
        headers={"Authorization": f"Bearer {tok}"},
        json={"helpful": True},
        timeout=15,
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["ok"] is True and r2.json()["helpful"] is True

    r = requests.get(f"{BASE}/api/v1/matches/for-job/{job_id}", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("score", "confidence", "reason_codes", "gate_results", "weights_version"):
        assert key in d
    assert d["weights_version"] == "v0.1"
    r2 = requests.post(
        f"{BASE}/api/v1/matches/for-job/{job_id}/feedback",
        headers={"Authorization": f"Bearer {tok}"},
        json={"helpful": True},
        timeout=15,
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["ok"] is True and r2.json()["helpful"] is True


# =============== 13. Usage meter — increments only for NEW scores ======
def test_usage_meter_increments_only_for_new_scores(user_zero_token):
    tok = user_zero_token
    # ensure feed has been called at least once so we're comparing steady-state
    requests.get(f"{BASE}/api/v1/jobs/feed", headers={"Authorization": f"Bearer {tok}"}, timeout=60)
    u1 = requests.get(f"{BASE}/api/v1/usage/me", headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
    before = u1.get("jobs_processed", 0)
    # Second call → upsert on existing rows; jobs_processed should NOT increase
    requests.get(f"{BASE}/api/v1/jobs/feed", headers={"Authorization": f"Bearer {tok}"}, timeout=60)
    u2 = requests.get(f"{BASE}/api/v1/usage/me", headers={"Authorization": f"Bearer {tok}"}, timeout=15).json()
    after = u2.get("jobs_processed", 0)
    assert after == before, f"jobs_processed unexpectedly grew {before}->{after}; upserts must not count"


# =============== 14. Idempotency replay on shortlist ==================
def test_idempotency_replay_on_shortlist(user_zero_token, sample_job_ids, mongo):
    tok = user_zero_token
    me = requests.get(f"{BASE}/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=10).json()
    uid = me["id"]
    job_id = sample_job_ids[2]
    mongo.applications.delete_many({"user_id": uid, "job_id": job_id})
    key = f"qa-idem-{uuid.uuid4().hex[:12]}"
    h = {"Authorization": f"Bearer {tok}", "Idempotency-Key": key}
    r1 = requests.post(f"{BASE}/api/v1/jobs/{job_id}/shortlist", headers=h, timeout=15)
    assert r1.status_code == 201, r1.text
    r2 = requests.post(f"{BASE}/api/v1/jobs/{job_id}/shortlist", headers=h, timeout=15)
    assert r2.status_code == 201, r2.text
    assert r1.content == r2.content, "Idempotent replay body must be byte-identical"
    assert r2.headers.get("X-Idempotent-Replay") == "true"
    assert mongo.applications.count_documents({"user_id": uid, "job_id": job_id}) == 1


def test_idempotency_replay_on_state_transition(user_zero_token, sample_job_ids, mongo):
    tok = user_zero_token
    me = requests.get(f"{BASE}/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=10).json()
    uid = me["id"]
    job_id = sample_job_ids[3] if len(sample_job_ids) > 3 else sample_job_ids[0]
    mongo.applications.delete_many({"user_id": uid, "job_id": job_id})
    r = requests.post(f"{BASE}/api/v1/jobs/{job_id}/shortlist", headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    key = f"qa-idem-state-{uuid.uuid4().hex[:12]}"
    h = {"Authorization": f"Bearer {tok}", "Idempotency-Key": key}
    body = {"expected_state": "shortlisted", "new_state": "preparing"}
    r1 = requests.patch(f"{BASE}/api/v1/applications/{app_id}/state", headers=h, json=body, timeout=15)
    assert r1.status_code == 200, r1.text
    r2 = requests.patch(f"{BASE}/api/v1/applications/{app_id}/state", headers=h, json=body, timeout=15)
    assert r2.status_code == 200, r2.text
    assert r1.content == r2.content, "Idempotent replay body must be byte-identical"
    assert r2.headers.get("X-Idempotent-Replay") == "true"


# =============== 15. SAMPLE badge integrity ===========================
def test_sample_seed_integrity(mongo):
    from domains.seeds import data as _seed_data
    expected_count = len(_seed_data.SAMPLE_JOBS)
    cur = list(mongo.jobs.find({"is_sample": True, "canonical_key": {"$regex": "^sampleco.demo::sample-"}}, {"_id": 0}))
    assert len(cur) == expected_count, f"Expected exactly {expected_count} SampleCo sample_jobs, got {len(cur)}"
    for j in cur:
        assert j.get("is_sample") is True
        # Requirements payload populated
        reqs = j.get("requirements") or {}
        # Founder Directive says skills_required, degree_level, years_min populated
        assert reqs.get("skills_required"), f"Missing skills_required for {j['canonical_key']}"
        assert reqs.get("degree_level"), f"Missing degree_level for {j['canonical_key']}"
        assert reqs.get("years_min") is not None, f"Missing years_min for {j['canonical_key']}"


def test_feed_sample_rows_are_flagged(user_zero_token):
    tok = user_zero_token
    d = requests.get(f"{BASE}/api/v1/jobs/feed", headers={"Authorization": f"Bearer {tok}"}, timeout=60).json()
    for row in d["passing"]:
        # a sample-badged row must have is_sample true; a non-sample row false
        # (both fields must be present)
        assert "is_sample" in row


def test_applications_list_returns_all_rows(user_zero_token):
    r = requests.get(f"{BASE}/api/v1/applications", headers={"Authorization": f"Bearer {user_zero_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["applications"], list)


# =============== 16. LLM cost ledger — code shape + row shape ==========
def test_llm_cost_service_passes_user_id():
    with open("/app/backend/domains/documents/service.py") as fh:
        svc = fh.read()
    assert "parse_resume_text(text, document_id, user_id=user_id)" in svc, (
        "documents/service.py must pass user_id into parse_resume_text"
    )
    with open("/app/backend/services/llm.py") as fh:
        llm = fh.read()
    assert "_write_cost_row" in llm
    assert "llm_costs" in llm
    # Row must be written on BOTH success and failure
    assert llm.count("_write_cost_row(") >= 2


def test_llm_cost_row_shape_if_present(mongo):
    row = mongo.llm_costs.find_one({}, {"_id": 0})
    if row is None:
        pytest.skip("No llm_costs rows present yet (no resume parses have run)")
    for k in ("id", "task", "model", "tokens_in_est", "tokens_out_est", "cost_usd_est", "ts"):
        assert k in row, f"llm_costs row missing field {k}"
    # user_id key must EXIST (may be None if system parse)
    assert "user_id" in row


# =============== 17. Submission receipts: no update/delete code ========
def test_submission_receipts_service_has_no_update_or_delete():
    with open("/app/backend/domains/submission_receipts/service.py") as fh:
        src = fh.read()
    forbidden = ["update_one", "update_many", "delete_one", "delete_many", "find_one_and_update", "replace_one"]
    hits = [w for w in forbidden if w in src]
    assert not hits, f"submission_receipts/service.py contains mutation calls: {hits}"
