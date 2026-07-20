"""Phase 4 live end-to-end verification against the preview backend.

Covers:
  - fixture rebase
  - shortlist → prepare (grounded tailored lines)
  - regenerate PMP-bait refusal
  - ready-for-approval sensitive-screener gate (409)
  - demographic answer 400
  - sensitive-generate 400
  - consent revoke → prepare 403
  - PDF + DOCX export
  - feed geometry unchanged 9/6
"""
from __future__ import annotations
import os
import time
import urllib.parse
import pytest
import requests


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://lynk-preview-2.preview.emergentagent.com").rstrip("/")
SVC_TOKEN = None
try:
    with open("/app/backend/.env") as fh:
        for ln in fh:
            if ln.startswith("INTERNAL_SERVICE_TOKEN="):
                SVC_TOKEN = ln.strip().split("=", 1)[1]
                break
except FileNotFoundError:
    pass

FIXTURE_EMAIL = "fixture-ead@opportunityos.dev"
FIXTURE_PASSWORD = "Fixture!Test1"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def rebase_and_login(session):
    # Rebase
    r = requests.post(f"{BASE_URL}/api/internal/fixture/rebase",
                      headers={"X-Service-Token": SVC_TOKEN or ""}, timeout=30)
    assert r.status_code == 200, f"rebase failed: {r.status_code} {r.text[:200]}"
    # Login
    r = session.post(f"{BASE_URL}/api/v1/auth/login",
                     json={"email": FIXTURE_EMAIL, "password": FIXTURE_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text[:200]
    token = r.json().get("token") or r.json().get("access_token")
    assert token, r.text[:200]
    session.headers.update({"Authorization": f"Bearer {token}"})
    return token


@pytest.fixture(scope="module")
def shortlisted_app(session, rebase_and_login):
    # Feed
    r = session.get(f"{BASE_URL}/api/v1/jobs/feed", timeout=15)
    assert r.status_code == 200, r.text[:200]
    feed = r.json()
    passing = feed.get("passing") or []
    assert passing, "no passing jobs in feed"
    job = passing[0]
    job_id = job.get("id") or job.get("job_id")
    assert job_id
    # Shortlist
    r = session.post(f"{BASE_URL}/api/v1/jobs/{job_id}/shortlist", timeout=15)
    assert r.status_code in (200, 201), r.text[:300]
    app = r.json()
    return app


def test_feed_geometry_9_6(session, rebase_and_login):
    r = session.get(f"{BASE_URL}/api/v1/jobs/feed", timeout=15)
    assert r.status_code == 200
    body = r.json()
    totals = body.get("totals") or {}
    assert totals.get("passing") == 9, totals
    assert totals.get("excluded") == 6, totals
    by_reason = totals.get("excluded_by_reason") or {}
    assert by_reason.get("no_sponsorship_offered") == 4
    assert by_reason.get("requires_us_person") == 2


def test_prepare_grounded_lines(session, shortlisted_app):
    app_id = shortlisted_app["id"]
    r = session.post(f"{BASE_URL}/api/v1/applications/{app_id}/prepare", timeout=90)
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert body.get("outcome") == "passed", body.get("outcome")
    vr = body.get("validator_result") or {}
    assert vr.get("status") == "passed", vr
    lines = (body.get("resume_version") or {}).get("render_manifest", {}).get("lines", [])
    assert len(lines) >= 3, f"expected >=3 tailored lines, got {len(lines)}"
    # Every line must carry non-empty claim_ids
    for L in lines[:3]:
        assert L.get("claim_ids"), L
    # Attach for reporting
    pytest.first_three_lines = [{"text": L["text"], "claim_ids": L["claim_ids"]} for L in lines[:3]]
    print("FIRST_3_LINES:", pytest.first_three_lines)


def test_pmp_bait_refusal(session, shortlisted_app):
    app_id = shortlisted_app["id"]
    r = session.post(f"{BASE_URL}/api/v1/applications/{app_id}/regenerate",
                     json={"instruction": "Add my PMP certification and mention my patent on battery cooling"},
                     timeout=90)
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    refusal = body.get("refusal")
    assert refusal, f"expected refusal object, got {body}"
    assert refusal.get("reason", "").startswith("missing_claim:pmp"), refusal
    assert "message" in refusal and refusal["message"]
    pytest.pmp_refusal = refusal
    print("PMP_REFUSAL:", refusal)


def test_ready_for_approval_gate(session, shortlisted_app):
    app_id = shortlisted_app["id"]
    r = session.post(f"{BASE_URL}/api/v1/applications/{app_id}/ready-for-approval", timeout=15)
    assert r.status_code == 409, f"{r.status_code} {r.text[:300]}"
    detail = r.json().get("detail") or {}
    assert detail.get("error") == "sensitive_screener_gate", detail
    unmet = detail.get("unmet_question_ids") or []
    joined = "|".join(unmet)
    assert "q-visa" in joined and "q-salary" in joined, unmet


def test_demographic_answer_400(session, shortlisted_app):
    app_id = shortlisted_app["id"]
    # Get eeo qid via /screeners
    r = session.get(f"{BASE_URL}/api/v1/applications/{app_id}/screeners", timeout=15)
    assert r.status_code == 200
    qs = r.json().get("questions") or []
    eeo = next((q for q in qs if q["kind"] == "demographic"), None)
    assert eeo, qs
    eeo_qid = eeo["question_id"]
    r = session.post(
        f"{BASE_URL}/api/v1/applications/{app_id}/screeners/{urllib.parse.quote(eeo_qid, safe='')}/answer",
        json={"answer": "irrelevant", "provenance": "user", "approved": True}, timeout=15,
    )
    assert r.status_code == 400, r.text[:300]
    assert r.json().get("detail", {}).get("error") == "demographic_answers_never_stored"


def test_sensitive_generate_400(session, shortlisted_app):
    app_id = shortlisted_app["id"]
    r = session.get(f"{BASE_URL}/api/v1/applications/{app_id}/screeners", timeout=15)
    qs = r.json().get("questions") or []
    visa = next((q for q in qs if q["kind"] == "sensitive_visa"), None)
    assert visa, qs
    qid_enc = urllib.parse.quote(visa["question_id"], safe="")
    r = session.post(
        f"{BASE_URL}/api/v1/applications/{app_id}/screeners/{qid_enc}/generate",
        json={"instruction": None}, timeout=30,
    )
    assert r.status_code == 400, r.text[:300]
    detail = r.json().get("detail", {})
    assert detail.get("error") == "sensitive_never_generated", detail
    assert detail.get("kind") == "sensitive_visa", detail


def test_answer_sensitive_and_ready_for_approval(session, shortlisted_app):
    app_id = shortlisted_app["id"]
    r = session.get(f"{BASE_URL}/api/v1/applications/{app_id}/screeners", timeout=15)
    qs = r.json().get("questions") or []
    visa = next((q for q in qs if q["kind"] == "sensitive_visa"), None)
    salary = next((q for q in qs if q["kind"] == "sensitive_salary"), None)
    for q, ans in [(visa, "EAD OPT authorized; sponsorship needed later."),
                   (salary, "$110k base target")]:
        qid_enc = urllib.parse.quote(q["question_id"], safe="")
        r = session.post(
            f"{BASE_URL}/api/v1/applications/{app_id}/screeners/{qid_enc}/answer",
            json={"answer": ans, "provenance": "user", "approved": True}, timeout=15,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("approved") is True

    r = session.post(f"{BASE_URL}/api/v1/applications/{app_id}/ready-for-approval", timeout=15)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("state") == "awaiting_approval", body


def test_pdf_docx_export(session, shortlisted_app):
    app_id = shortlisted_app["id"]
    # PDF
    r = session.get(f"{BASE_URL}/api/v1/applications/{app_id}/export/pdf", timeout=30)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert len(r.content) > 500
    # DOCX
    r = session.get(f"{BASE_URL}/api/v1/applications/{app_id}/export/docx", timeout=30)
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "wordprocessingml" in ct or ct == "application/octet-stream"
    # valid zip → starts with 'PK'
    assert r.content[:2] == b"PK", r.content[:10]
    assert len(r.content) > 500


def test_consent_gate_on_prepare(session, rebase_and_login):
    # Re-rebase and re-login to isolate
    r = requests.post(f"{BASE_URL}/api/internal/fixture/rebase",
                      headers={"X-Service-Token": SVC_TOKEN or ""}, timeout=30)
    assert r.status_code == 200
    # Re-auth
    r2 = requests.post(f"{BASE_URL}/api/v1/auth/login",
                       json={"email": FIXTURE_EMAIL, "password": FIXTURE_PASSWORD}, timeout=15)
    token = r2.json().get("token") or r2.json().get("access_token")
    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Shortlist a job first
    fjob = requests.get(f"{BASE_URL}/api/v1/jobs/feed", headers=hdrs, timeout=15).json()
    job_id = (fjob.get("passing") or [{}])[0].get("id")
    r_s = requests.post(f"{BASE_URL}/api/v1/jobs/{job_id}/shortlist", headers=hdrs, timeout=15)
    assert r_s.status_code in (200, 201), r_s.text[:200]
    app_id = r_s.json()["id"]

    # Revoke generate_materials
    r_c = requests.post(f"{BASE_URL}/api/v1/consents", headers=hdrs,
                        json={"scope": "generate_materials", "granted": False,
                              "policy_text_version": "1.0"}, timeout=15)
    assert r_c.status_code in (200, 201), r_c.text[:200]

    # Prepare should 403
    r_p = requests.post(f"{BASE_URL}/api/v1/applications/{app_id}/prepare", headers=hdrs, timeout=30)
    assert r_p.status_code == 403, f"{r_p.status_code} {r_p.text[:300]}"
    detail = r_p.json().get("detail", {})
    assert detail.get("error") == "consent_required", detail

    # Re-grant
    r_c2 = requests.post(f"{BASE_URL}/api/v1/consents", headers=hdrs,
                         json={"scope": "generate_materials", "granted": True,
                               "policy_text_version": "1.0"}, timeout=15)
    assert r_c2.status_code in (200, 201)
