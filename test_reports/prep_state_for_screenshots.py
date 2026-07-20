"""Pre-Playwright driver: rebase → login → drive one packet to submitted+attested.
Prints the resulting app_id + token so the Playwright script can consume them.
"""
import json
import uuid
import urllib.parse
import requests


def _read(path, key):
    for line in open(path):
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


BASE = _read("/app/frontend/.env", "REACT_APP_BACKEND_URL")
SVC = _read("/app/backend/.env", "INTERNAL_SERVICE_TOKEN")


def hdr(t, idem=None):
    h = {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


def main():
    requests.post(f"{BASE}/api/internal/fixture/rebase", headers={"X-Service-Token": SVC}, timeout=30)
    lg = requests.post(f"{BASE}/api/v1/auth/login",
                       json={"email": "fixture-ead@opportunityos.dev",
                             "password": "Fixture!Test1"}, timeout=15).json()
    token = lg["access_token"]
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
    requests.post(f"{BASE}/api/v1/applications/{app_id}/approve",
                  headers=hdr(token), json={}, timeout=15)
    requests.post(f"{BASE}/api/v1/applications/{app_id}/submit",
                  headers=hdr(token, f"sub-{app_id}"), json={}, timeout=15)
    att = requests.post(f"{BASE}/api/v1/applications/{app_id}/attest",
                        headers=hdr(token, f"att-{app_id}"), json={}, timeout=15).json()
    print(json.dumps({
        "token": token,
        "app_id": app_id,
        "job_id": job_id,
        "receipt_hash_short": att["receipt"]["materials_hash_short"],
    }))


if __name__ == "__main__":
    main()
