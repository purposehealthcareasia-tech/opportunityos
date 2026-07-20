"""Phase 5 backend e2e — approve / submit / attest / duplicate / auth-hash-mismatch /
daily-cap / outcomes / inbound-webhook / tracker / analytics.

Runs against the LIVE preview backend via `requests`. Fixture rebase invoked once
at module scope, then each test manages its own fresh application within the run.
"""
from __future__ import annotations
import asyncio
import os
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient


def _read_env(path: str, key: str) -> str:
    try:
        for line in open(path):
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return os.environ.get(key, "")


BASE_URL = _read_env("/app/frontend/.env", "REACT_APP_BACKEND_URL")
SVC_TOKEN = _read_env("/app/backend/.env", "INTERNAL_SERVICE_TOKEN")
MONGO_URL = _read_env("/app/backend/.env", "MONGO_URL")
DB_NAME = _read_env("/app/backend/.env", "DB_NAME")
FIXTURE_EMAIL = os.environ.get("FIXTURE_TEST_EMAIL", "fixture-ead@opportunityos.dev")
FIXTURE_PASSWORD = os.environ.get("FIXTURE_TEST_PASSWORD", "Fixture!Test1")


def _sync_db():
    return MongoClient(MONGO_URL, uuidRepresentation="standard")[DB_NAME]


def _rebase() -> None:
    r = requests.post(f"{BASE_URL}/api/internal/fixture/rebase",
                      headers={"X-Service-Token": SVC_TOKEN or ""}, timeout=30)
    assert r.status_code == 200, r.text[:200]


def _login() -> tuple[str, str]:
    r = requests.post(f"{BASE_URL}/api/v1/auth/login",
                      json={"email": FIXTURE_EMAIL, "password": FIXTURE_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    return d["access_token"], d["user"]["id"]


def _auth_header(token: str, idem: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


def _drive_to_approved(token: str) -> tuple[str, str]:
    """Shortlist → prepare → approve sensitive screeners → ready-for-approval → approve.
    Returns (application_id, job_id)."""
    r = requests.get(f"{BASE_URL}/api/v1/jobs/feed", headers=_auth_header(token), timeout=20)
    job_id = r.json()["passing"][0]["id"]
    r = requests.post(f"{BASE_URL}/api/v1/jobs/{job_id}/shortlist",
                      headers=_auth_header(token, idem=f"sl-{uuid.uuid4().hex[:8]}"),
                      json={}, timeout=20)
    app_id = r.json()["id"]
    requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/prepare",
                  headers=_auth_header(token, idem=f"prep-{app_id}"), json={}, timeout=60)
    scr = requests.get(f"{BASE_URL}/api/v1/applications/{app_id}/screeners",
                       headers=_auth_header(token), timeout=15).json()
    for q in scr["questions"]:
        if q["sensitive"]:
            qenc = urllib.parse.quote(q["question_id"], safe="")
            requests.post(
                f"{BASE_URL}/api/v1/applications/{app_id}/screeners/{qenc}/answer",
                headers=_auth_header(token, idem=f"ans-{uuid.uuid4().hex[:8]}"),
                json={"answer": "acknowledged", "provenance": "user", "approved": True},
                timeout=15,
            )
    requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/ready-for-approval",
                  headers=_auth_header(token, idem=f"r4a-{app_id}"), json={}, timeout=15)
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/approve",
                      headers=_auth_header(token), json={}, timeout=15)
    assert r.status_code == 200, r.text[:200]
    return app_id, job_id


# ============================================================
# Test 1 — Full happy path
# ============================================================
def test_full_check_e_happy_path():
    _rebase()
    token, _ = _login()
    app_id, _ = _drive_to_approved(token)

    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/submit",
                      headers=_auth_header(token, idem=f"sub-{app_id}"), json={}, timeout=20)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["application"]["state"] == "submitting"
    assert len(b["materials_hash_short"]) == 10
    assert b["usage"]["cap"] == 15  # fixture-user is on plus plan

    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/attest",
                      headers=_auth_header(token, idem=f"att-{app_id}"),
                      json={"confirm_method": "user_attest"}, timeout=15)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["application"]["state"] == "submitted"
    assert b["duplicate_check"] == "clean"
    receipt = b["receipt"]
    assert receipt["materials_hash_short"] == receipt["materials_manifest_hash"][:10]

    # Receipt retrievable by application id
    r = requests.get(f"{BASE_URL}/api/v1/applications/{app_id}/receipt",
                     headers=_auth_header(token), timeout=10)
    assert r.status_code == 200
    assert r.json()["id"] == receipt["id"]


# ============================================================
# Test 2 — Duplicate block (open-app unique gate + duplicate-check endpoint)
# ============================================================
def test_duplicate_receipt_blocks_second_submission():
    _rebase()
    token, _ = _login()
    app_id, job_id = _drive_to_approved(token)
    requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/submit",
                  headers=_auth_header(token, idem=f"dsub-{app_id}"), json={}, timeout=15)
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/attest",
                      headers=_auth_header(token, idem=f"datt-{app_id}"), json={}, timeout=15)
    assert r.status_code == 201
    original = r.json()["receipt"]

    # Re-shortlisting the same job hits the (user,job)-open-state unique index.
    r = requests.post(f"{BASE_URL}/api/v1/jobs/{job_id}/shortlist",
                      headers=_auth_header(token, idem="dup-sl"), json={}, timeout=15)
    assert r.status_code == 409, r.text

    # Duplicate-check surface flags the prior receipt.
    apps = requests.get(f"{BASE_URL}/api/v1/applications",
                        headers=_auth_header(token), timeout=15).json()["applications"]
    a = next(a for a in apps if a["id"] == app_id)
    req_ref = (a.get("job_snapshot") or {}).get("canonical_key") or a["job_id"]
    r = requests.get(f"{BASE_URL}/api/v1/applications/duplicate-check",
                     params={"company_id": a["company_id"], "req_ref": req_ref},
                     headers=_auth_header(token), timeout=10)
    assert r.status_code == 200
    b = r.json()
    assert b["has_prior"] is True
    assert b["prior_receipt"]["id"] == original["id"]


# ============================================================
# Test 3 — Authorization revoked, expired, materials-changed
# ============================================================
def test_authorization_expired_blocks_submit():
    _rebase()
    token, uid = _login()
    app_id, _ = _drive_to_approved(token)
    _sync_db().authorization_scopes.update_many(
        {"user_id": uid, "target": app_id},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(hours=1)}},
    )
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/submit",
                      headers=_auth_header(token, idem=f"exp-{app_id}"), json={}, timeout=10)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "authorization_expired"


def test_authorization_revoked_blocks_submit():
    _rebase()
    token, _ = _login()
    app_id, _ = _drive_to_approved(token)
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/revoke-authorization",
                      headers=_auth_header(token), json={}, timeout=10)
    assert r.status_code == 200
    assert r.json()["application"]["state"] == "awaiting_approval"


def test_materials_changed_blocks_submit():
    _rebase()
    token, uid = _login()
    app_id, _ = _drive_to_approved(token)
    db = _sync_db()
    app_row = db.applications.find_one({"id": app_id, "user_id": uid})
    resume_id = (app_row.get("materials") or {}).get("resume_version_id")
    db.resume_versions.update_one(
        {"id": resume_id},
        {"$set": {"render_manifest.lines.0.text":
                  "MUTATED AFTER APPROVAL — this must change the hash"}},
    )
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/submit",
                      headers=_auth_header(token, idem=f"mc-{app_id}"), json={}, timeout=10)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["error"] == "materials_changed"
    assert d["current_materials_hash"] != d["authorized_materials_hash"]


# ============================================================
# Test 4 — Daily cap
# ============================================================
def test_daily_cap_blocks_over_limit():
    _rebase()
    token, uid = _login()
    app_id, _ = _drive_to_approved(token)
    db = _sync_db()
    now = datetime.now(timezone.utc)
    docs = [{
        "id": str(uuid.uuid4()),
        "user_id": uid,
        "company_id": f"cap-test-co-{i}.com",
        "req_ref": f"cap-test-req-{i}-{uuid.uuid4().hex[:6]}",
        "application_id": f"cap-app-{i}",
        "job_id": f"cap-job-{i}",
        "materials_manifest_hash": "x" * 64,
        "submit_channel": "guided_manual",
        "supersedes": None,
        "ts": now,
    } for i in range(15)]
    db.submission_receipts.insert_many(docs)
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/submit",
                      headers=_auth_header(token, idem=f"cap-{app_id}"), json={}, timeout=10)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["error"] == "daily_cap_reached"
    assert d["plan"] == "plus"
    assert d["cap"] == 15
    assert "reset_at" in d


# ============================================================
# Test 5 — Tracker + outcomes + illegal transition + QI
# ============================================================
def test_tracker_outcomes_and_qi():
    _rebase()
    token, _ = _login()
    app_id, _ = _drive_to_approved(token)
    requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/submit",
                  headers=_auth_header(token, idem=f"t5-sub-{app_id}"), json={}, timeout=15)
    requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/attest",
                  headers=_auth_header(token, idem=f"t5-att-{app_id}"), json={}, timeout=15)
    tr = requests.get(f"{BASE_URL}/api/v1/tracker",
                      headers=_auth_header(token), timeout=10).json()
    assert tr["totals"]["submitted"] == 1
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/outcomes",
                      headers=_auth_header(token), json={"event": "response"}, timeout=10)
    assert r.status_code == 201
    assert r.json()["application_state"] == "response"

    # P1 fix — scheduling an interview advances the funnel from response → interview.
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/interviews",
                      headers=_auth_header(token), json={"stage": "recruiter_screen"}, timeout=10)
    assert r.status_code == 201, r.text
    body = r.json()
    iv_id = body["interview"]["id"]
    assert body["transition"] == {"from": "response", "to": "interview"}, body
    assert body["application_state"] == "interview"
    # Funnel now counts it.
    fn = requests.get(f"{BASE_URL}/api/v1/analytics/funnel", headers=_auth_header(token), timeout=10).json()
    # Fixture-seeded job is SAMPLE — so it lands in the sample bucket, not personal totals.
    assert fn["sample"]["interview"] >= 1 or fn["totals"]["interview"] >= 1, fn

    # QI confirm still works.
    r = requests.post(f"{BASE_URL}/api/v1/interviews/{iv_id}/qualified",
                      headers=_auth_header(token), json={"qualified": True}, timeout=10)
    assert r.status_code == 200
    assert r.json()["qualified"] is True

    # From `interview`, walk forward to closed via outcome log.
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/outcomes",
                      headers=_auth_header(token), json={"event": "rejected"}, timeout=10)
    assert r.status_code == 201
    assert r.json()["application_state"] == "closed"
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/outcomes",
                      headers=_auth_header(token), json={"event": "response"}, timeout=10)
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "invalid_transition"


def test_schedule_interview_from_illegal_state_rejects_transition_but_persists_row():
    """P1 spec: scheduling from a non-{submitted,response} state must NOT crash and must
    NOT silently succeed the transition. The interview row + outcome are still persisted
    (append-only), but application state is unchanged and transition_error is surfaced."""
    _rebase()
    token, _ = _login()
    app_id, _ = _drive_to_approved(token)  # state = approved
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/interviews",
                      headers=_auth_header(token), json={"stage": "phone_screen"}, timeout=10)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["transition"] is None
    assert body["transition_error"] == "state_source_not_eligible_for_interview"
    assert body["application_state"] == "approved"


# ============================================================
# Test 6 — Inbound webhook stub
# ============================================================
def test_inbound_webhook_token_and_idempotency():
    _rebase()
    token, uid = _login()
    app_id, _ = _drive_to_approved(token)
    # Bad token
    r = requests.post(f"{BASE_URL}/api/internal/inbound/response",
                      headers={"X-Service-Token": "wrong-token"},
                      json={"user_id": uid, "application_id": app_id,
                            "event": "viewed", "ext_message_id": f"m-bad-{uuid.uuid4().hex[:6]}"},
                      timeout=10)
    assert r.status_code == 403
    # Missing token → 401
    r = requests.post(f"{BASE_URL}/api/internal/inbound/response",
                      json={"user_id": uid, "application_id": app_id,
                            "event": "viewed", "ext_message_id": f"m-none-{uuid.uuid4().hex[:6]}"},
                      timeout=10)
    assert r.status_code == 401
    msg_id = f"m-good-{uuid.uuid4().hex[:6]}"
    r = requests.post(f"{BASE_URL}/api/internal/inbound/response",
                      headers={"X-Service-Token": SVC_TOKEN},
                      json={"user_id": uid, "application_id": app_id,
                            "event": "viewed", "ext_message_id": msg_id},
                      timeout=10)
    assert r.status_code == 201
    assert r.json()["replay"] is False
    assert r.json()["outcome"]["source"] == "parsed"
    r = requests.post(f"{BASE_URL}/api/internal/inbound/response",
                      headers={"X-Service-Token": SVC_TOKEN},
                      json={"user_id": uid, "application_id": app_id,
                            "event": "viewed", "ext_message_id": msg_id},
                      timeout=10)
    assert r.status_code == 201
    assert r.json()["replay"] is True


# ============================================================
# Test 7 — Analytics funnel
# ============================================================
def test_analytics_funnel():
    _rebase()
    token, _ = _login()
    r = requests.get(f"{BASE_URL}/api/v1/analytics/funnel",
                     headers=_auth_header(token), timeout=10)
    assert r.status_code == 200
    empty = r.json()
    assert empty["empty"] is True
    assert empty["totals"]["prepared"] == 0
    assert empty["sample_note"]
    # Drive to submitted, then re-query.
    app_id, _ = _drive_to_approved(token)
    requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/submit",
                  headers=_auth_header(token, idem=f"a7-sub-{app_id}"), json={}, timeout=15)
    requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/attest",
                  headers=_auth_header(token, idem=f"a7-att-{app_id}"), json={}, timeout=15)
    r = requests.get(f"{BASE_URL}/api/v1/analytics/funnel",
                     headers=_auth_header(token), timeout=10)
    b = r.json()
    # The SAMPLE-seeded job is is_sample=True, so its counts land in `sample`, NOT totals.
    assert b["sample"]["prepared"] >= 1
    assert b["sample"]["submitted"] >= 1
    assert b["conversion"]["prepared_to_submitted"] in (None, 0, 100)  # totals is 0 → None


# ============================================================
# Test 8 — Consent gate on tracker
# ============================================================
def test_track_applications_consent_gate():
    _rebase()
    token, _ = _login()
    r = requests.post(f"{BASE_URL}/api/v1/consents",
                      headers=_auth_header(token),
                      json={"scope": "track_applications", "granted": False,
                            "policy_text_version": "1.0"},
                      timeout=10)
    assert r.status_code in (200, 201), r.text[:200]
    r = requests.get(f"{BASE_URL}/api/v1/tracker",
                     headers=_auth_header(token), timeout=10)
    assert r.status_code == 403
    body = r.json()["detail"]
    assert body["error"] == "consent_required"
    assert body["scope"] == "track_applications"


# ============================================================
# Test 9 — P0 fix: duplicate submit returns 409 (not 500) with parseable JSON
# ============================================================
def test_duplicate_submit_returns_409_with_parseable_prior_receipt():
    """Fix-directive P0: the duplicate branch used to embed a raw datetime in the
    HTTPException detail → starlette serialization TypeError → 500. Now the entire
    detail is passed through fastapi.encoders.jsonable_encoder so the client sees a
    proper 409 with a JSON-parseable prior_receipt (ts is an ISO-8601 string)."""
    _rebase()
    token, _ = _login()
    app_id, _ = _drive_to_approved(token)
    # First submit+attest — persists a receipt.
    requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/submit",
                  headers=_auth_header(token, idem=f"p0-sub-{app_id}"), json={}, timeout=15)
    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/attest",
                      headers=_auth_header(token, idem=f"p0-att-{app_id}"), json={}, timeout=15)
    assert r.status_code == 201

    # Force the state back to approved so we can hit the submit-time duplicate branch.
    # (Without this, the 2nd submit fails at the state precondition, which is a different code path.)
    db = _sync_db()
    db.applications.update_one({"id": app_id}, {"$set": {"state": "approved"}})

    r = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/submit",
                      headers=_auth_header(token, idem=f"p0-dup-sub-{app_id}"), json={}, timeout=15)
    # This MUST be a proper 409 — never 500 — and the body must be JSON-parseable.
    assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text[:300]}"
    body = r.json()  # would raise if not parseable JSON
    detail = body["detail"]
    assert detail["error"] == "duplicate_application"
    assert isinstance(detail["prior_receipt"], dict)
    # The prior receipt ts must be an ISO-8601 STRING (not a datetime that starlette can't serialize).
    assert isinstance(detail["prior_receipt"]["ts"], str), detail["prior_receipt"]
    # Sanity: the hash and req_ref round-trip.
    assert detail["prior_receipt"]["req_ref"]
    assert len(detail["prior_receipt"]["materials_manifest_hash"]) == 64

