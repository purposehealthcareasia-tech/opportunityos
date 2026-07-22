"""Drive app to awaiting_approval via API for UI test.

Reads INTERNAL_SERVICE_TOKEN from the environment (never hardcoded). Run as:
    INTERNAL_SERVICE_TOKEN=$(awk -F= '/^INTERNAL_SERVICE_TOKEN=/{print $2}' \
        /app/backend/.env) python /app/test_reports/_drive_awaiting.py
"""
import json, os, sys, urllib.parse, uuid, requests

BASE = os.environ.get("APP_BASE_URL", "https://lynk-preview-2.preview.emergentagent.com")
SVC = os.environ.get("INTERNAL_SERVICE_TOKEN")
if not SVC:
    sys.exit("INTERNAL_SERVICE_TOKEN env var is required — refusing to run without it.")

def h(t, i=None):
    d = {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}
    if i: d["Idempotency-Key"] = i
    return d

requests.post(f"{BASE}/api/internal/fixture/rebase", headers={"X-Service-Token": SVC})
r = requests.post(f"{BASE}/api/v1/auth/login",
    json={"email": "fixture-ead@opportunityos.dev", "password": "Fixture!Test1"})
tok = r.json()["access_token"]
feed = requests.get(f"{BASE}/api/v1/jobs/feed", headers=h(tok)).json()
job_id = feed["passing"][0]["id"]
r = requests.post(f"{BASE}/api/v1/jobs/{job_id}/shortlist", headers=h(tok, "sl-ui"), json={})
app_id = r.json()["id"]
requests.post(f"{BASE}/api/v1/applications/{app_id}/prepare", headers=h(tok, f"prep-{app_id}"), json={}, timeout=60)
scr = requests.get(f"{BASE}/api/v1/applications/{app_id}/screeners", headers=h(tok)).json()
for q in scr["questions"]:
    if q["sensitive"]:
        qenc = urllib.parse.quote(q["question_id"], safe="")
        requests.post(f"{BASE}/api/v1/applications/{app_id}/screeners/{qenc}/answer",
            headers=h(tok, f"ans-{uuid.uuid4().hex[:8]}"),
            json={"answer": "acknowledged", "provenance": "user", "approved": True})
requests.post(f"{BASE}/api/v1/applications/{app_id}/ready-for-approval",
    headers=h(tok, f"r4a-{app_id}"), json={})
print(f"APP_ID={app_id}")
