"""Live-API capture for Phase 5 fix-directive round 1.

Exercises P0 (dup-submit → 409 JSON-parseable) and P1 (interview scheduling
advances funnel + illegal-state edge). Prints verbatim response bodies for
inclusion in the test report.
"""
from __future__ import annotations
import json
import sys
import uuid
import urllib.parse
from datetime import datetime, timezone

import requests
from pymongo import MongoClient


def _read(path, key):
    for line in open(path):
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


BASE = _read("/app/frontend/.env", "REACT_APP_BACKEND_URL")
TOKEN = _read("/app/backend/.env", "INTERNAL_SERVICE_TOKEN")
MONGO_URL = _read("/app/backend/.env", "MONGO_URL")
DB_NAME = _read("/app/backend/.env", "DB_NAME")


def hdr(t, idem=None):
    h = {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


def rebase():
    r = requests.post(f"{BASE}/api/internal/fixture/rebase",
                      headers={"X-Service-Token": TOKEN}, timeout=30)
    print("rebase:", r.status_code)


def login():
    r = requests.post(f"{BASE}/api/v1/auth/login",
                      json={"email": "fixture-ead@opportunityos.dev",
                            "password": "Fixture!Test1"}, timeout=15)
    d = r.json()
    return d["access_token"], d["user"]["id"]


def drive_to_approved(token):
    fr = requests.get(f"{BASE}/api/v1/jobs/feed", headers=hdr(token), timeout=20).json()
    job_id = fr["passing"][0]["id"]
    sl = requests.post(f"{BASE}/api/v1/jobs/{job_id}/shortlist",
                       headers=hdr(token, f"sl-{uuid.uuid4().hex[:6]}"),
                       json={}, timeout=15).json()
    app_id = sl["id"]
    requests.post(f"{BASE}/api/v1/applications/{app_id}/prepare",
                  headers=hdr(token, f"prep-{app_id}"), json={}, timeout=60)
    scr = requests.get(f"{BASE}/api/v1/applications/{app_id}/screeners",
                       headers=hdr(token), timeout=15).json()
    for q in scr["questions"]:
        if q["sensitive"]:
            qenc = urllib.parse.quote(q["question_id"], safe="")
            requests.post(f"{BASE}/api/v1/applications/{app_id}/screeners/{qenc}/answer",
                          headers=hdr(token, f"ans-{uuid.uuid4().hex[:6]}"),
                          json={"answer": "acknowledged", "provenance": "user", "approved": True},
                          timeout=15)
    requests.post(f"{BASE}/api/v1/applications/{app_id}/ready-for-approval",
                  headers=hdr(token, f"r4a-{app_id}"), json={}, timeout=15)
    r = requests.post(f"{BASE}/api/v1/applications/{app_id}/approve",
                      headers=hdr(token), json={}, timeout=15)
    print("approve:", r.status_code, "state=", r.json()["application"]["state"])
    return app_id, job_id


def scenario_p0():
    print("=" * 70)
    print("SCENARIO P0 — duplicate-submit → 409 with JSON-parseable prior_receipt")
    print("=" * 70)
    rebase()
    token, uid = login()
    app_id, _ = drive_to_approved(token)
    requests.post(f"{BASE}/api/v1/applications/{app_id}/submit",
                  headers=hdr(token, f"p0-sub-{app_id}"), json={}, timeout=15)
    att = requests.post(f"{BASE}/api/v1/applications/{app_id}/attest",
                        headers=hdr(token, f"p0-att-{app_id}"), json={}, timeout=15)
    print("first attest:", att.status_code)
    receipt_id_original = att.json()["receipt"]["id"]
    print("original receipt id:", receipt_id_original)

    db = MongoClient(MONGO_URL, uuidRepresentation="standard")[DB_NAME]
    res = db.applications.update_one({"id": app_id}, {"$set": {"state": "approved"}})
    print("force-state-back-to-approved matched:", res.matched_count)

    r = requests.post(f"{BASE}/api/v1/applications/{app_id}/submit",
                      headers=hdr(token, f"p0-dupsub-{app_id}"), json={}, timeout=15)
    print("duplicate submit status:", r.status_code)
    print("duplicate submit raw response body:")
    print(r.text)
    print("--- json.loads round-trip ---")
    parsed = json.loads(r.text)
    print(json.dumps(parsed, indent=2))
    d = parsed["detail"]
    assert r.status_code == 409, r.status_code
    assert d["error"] == "duplicate_application", d
    assert isinstance(d["prior_receipt"], dict)
    assert isinstance(d["prior_receipt"]["ts"], str), type(d["prior_receipt"]["ts"])
    print("P0 assertions PASS: 409, duplicate_application, prior_receipt.ts is str")
    return parsed


def scenario_p1():
    print("=" * 70)
    print("SCENARIO P1 — interview scheduling advances funnel")
    print("=" * 70)
    rebase()
    token, uid = login()
    app_id, _ = drive_to_approved(token)
    requests.post(f"{BASE}/api/v1/applications/{app_id}/submit",
                  headers=hdr(token, f"p1-sub-{app_id}"), json={}, timeout=15)
    att = requests.post(f"{BASE}/api/v1/applications/{app_id}/attest",
                        headers=hdr(token, f"p1-att-{app_id}"), json={}, timeout=15)
    print("attest:", att.status_code, "state=", att.json()["application"]["state"])
    resp = requests.post(f"{BASE}/api/v1/applications/{app_id}/outcomes",
                         headers=hdr(token), json={"event": "response"}, timeout=10)
    print("outcomes response:", resp.status_code, "app_state=", resp.json()["application_state"])

    r = requests.post(f"{BASE}/api/v1/applications/{app_id}/interviews",
                      headers=hdr(token), json={"stage": "recruiter_screen"}, timeout=10)
    print("schedule_interview status:", r.status_code)
    body = r.json()
    print(json.dumps({k: body[k] for k in ("transition", "transition_error", "application_state")}, indent=2))
    assert r.status_code == 201, body
    assert body["transition"] == {"from": "response", "to": "interview"}, body
    assert body["application_state"] == "interview", body
    assert body["outcome"]["event"] == "interview_scheduled", body
    iv_id = body["interview"]["id"]

    fn = requests.get(f"{BASE}/api/v1/analytics/funnel", headers=hdr(token), timeout=10).json()
    print("funnel sample bucket:", fn.get("sample"))
    assert fn["sample"]["interview"] >= 1, fn

    r = requests.post(f"{BASE}/api/v1/interviews/{iv_id}/qualified",
                      headers=hdr(token), json={"qualified": True}, timeout=10)
    print("qualified:", r.status_code, r.json().get("qualified"))
    fn2 = requests.get(f"{BASE}/api/v1/analytics/funnel", headers=hdr(token), timeout=10).json()
    # qi_total is exposed at root of the funnel response (not nested in sample bucket).
    qi_total = fn2.get("qi_total") or fn2.get("sample", {}).get("qi_total", 0)
    print("funnel qi_total after QI confirm:", qi_total)
    assert qi_total >= 1, fn2
    print("P1 assertions PASS: transition to interview + sample.interview>=1 + qi_total>=1")


def scenario_p1_edge():
    print("=" * 70)
    print("SCENARIO P1 EDGE — schedule from illegal state (approved)")
    print("=" * 70)
    rebase()
    token, uid = login()
    app_id, _ = drive_to_approved(token)  # state = approved
    r = requests.post(f"{BASE}/api/v1/applications/{app_id}/interviews",
                      headers=hdr(token), json={"stage": "phone_screen"}, timeout=10)
    print("status:", r.status_code)
    body = r.json()
    print(json.dumps({k: body.get(k) for k in ("transition", "transition_error", "application_state", "outcome", "interview")}, indent=2, default=str))
    assert r.status_code == 201, body
    assert body["transition"] is None, body
    assert body["transition_error"] == "state_source_not_eligible_for_interview", body
    assert body["application_state"] == "approved", body
    # persistence check
    db = MongoClient(MONGO_URL, uuidRepresentation="standard")[DB_NAME]
    iv = db.interviews.find_one({"id": body["interview"]["id"]})
    oc = db.outcomes.find_one({"id": body["outcome"]["id"]})
    assert iv is not None and oc is not None, "interview and outcome must persist"
    print("P1 EDGE assertions PASS: 201, transition_error surfaced, row+outcome persisted")


if __name__ == "__main__":
    scenario_p0()
    print()
    scenario_p1()
    print()
    scenario_p1_edge()
    print("\nALL LIVE SCENARIOS PASSED")
