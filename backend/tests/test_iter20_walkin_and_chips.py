"""Iteration 20 — Focused regression per review_request.

Verifies the two main-agent fixes on top of iteration 19:
  * POST /api/v1/walkins  — 5 walkins with distinct employers all 201, 6th 429
                            (walkin:<uuid> synthetic job_id avoids dup-key)
  * GET  /api/v1/walkins/mine       — lists all 5 (newest first)
  * GET  /api/v1/applications       — 5 companion rows, route=walkin, job_id
                                      starts with 'walkin:'
"""
from __future__ import annotations
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL",
                          "https://lynk-preview-2.preview.emergentagent.com").rstrip("/")
EMAIL = "fixture-ead@opportunityos.dev"
PASSWORD = "Fixture!Test1"


def _svc_token():
    try:
        with open("/app/backend/.env") as f:
            for ln in f:
                if ln.startswith("INTERNAL_SERVICE_TOKEN="):
                    return ln.strip().split("=", 1)[1]
    except Exception:
        pass
    return None


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    tok = _svc_token()
    if tok:
        requests.post(f"{BASE_URL}/api/internal/fixture/rebase",
                      headers={"X-Service-Token": tok}, timeout=30)
    # NB: /api/internal/fixture/rebase does NOT wipe the walkins collection
    # (see backend/domains/seeds/seeder.py::_rebase_fixture_user to_wipe list).
    # Wipe directly so we can validate the 5→201 / 6th→429 contract.
    try:
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        if not mongo_url or not db_name:
            with open("/app/backend/.env") as f:
                for ln in f:
                    if ln.startswith("MONGO_URL=") and not mongo_url:
                        mongo_url = ln.strip().split("=", 1)[1]
                    if ln.startswith("DB_NAME=") and not db_name:
                        db_name = ln.strip().split("=", 1)[1]

        async def _wipe():
            c = AsyncIOMotorClient(mongo_url)
            db = c[db_name]
            uid = "c9f47fd8-fd59-4df9-8c9c-b7ff68fb4785"
            await db.walkins.delete_many({"user_id": uid})
            await db.applications.delete_many({"user_id": uid, "route": "walkin"})
        asyncio.get_event_loop().run_until_complete(_wipe())
    except Exception as e:
        print(f"walkin wipe failed: {e}")
    r = s.post(f"{BASE_URL}/api/v1/auth/login",
               json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    at = r.json().get("access_token")
    if at:
        s.headers["Authorization"] = f"Bearer {at}"
    csrf = s.cookies.get("oppos_csrf")
    if csrf:
        s.headers["X-CSRF-Token"] = csrf
    return s


class TestWalkinRegression:
    """Review-request: 5 walkins distinct employers → 201 x5, 6th → 429."""

    def test_five_walkins_all_201_and_sixth_429(self, client):
        run = uuid.uuid4().hex[:6]
        results = []
        for i in range(5):
            r = client.post(
                f"{BASE_URL}/api/v1/walkins",
                json={
                    "employer": f"TEST_Walkin_{run}_{i}",
                    "location": "Phoenix, AZ",
                    "outcome": "submitted",
                    "notes": f"iter20 regression {i}",
                },
                timeout=30,
            )
            results.append((i, r.status_code, r.text[:200]))
            assert r.status_code in (200, 201), \
                f"walkin #{i} expected 201, got {r.status_code}: {r.text}"

        # 6th → 429 walkin_rate_limited
        r6 = client.post(
            f"{BASE_URL}/api/v1/walkins",
            json={"employer": f"TEST_Walkin_{run}_5",
                  "location": "Phoenix, AZ", "outcome": "submitted"},
            timeout=30,
        )
        assert r6.status_code == 429, \
            f"6th walkin expected 429, got {r6.status_code}: {r6.text}"
        det = (r6.json().get("detail") or r6.json())
        val = det if isinstance(det, str) else (det.get("error") or "")
        assert "walkin_rate_limited" in str(val), det

    def test_mine_lists_five_newest_first(self, client):
        r = client.get(f"{BASE_URL}/api/v1/walkins/mine", timeout=30)
        assert r.status_code == 200, r.text
        items = r.json()
        items = items.get("walkins") if isinstance(items, dict) else items
        assert isinstance(items, list)
        # at least the 5 we just created should be present (module rebased once)
        test_rows = [w for w in items
                     if (w.get("employer") or "").startswith("TEST_Walkin_")]
        assert len(test_rows) >= 5, f"expected >=5, got {len(test_rows)}"
        # newest first — created_at DESC
        ts = [w.get("created_at") for w in test_rows]
        if all(ts):
            assert ts == sorted(ts, reverse=True), f"not DESC: {ts}"

    def test_applications_contains_walkin_route_rows(self, client):
        r = client.get(f"{BASE_URL}/api/v1/applications", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        apps = body.get("applications") if isinstance(body, dict) else body
        assert isinstance(apps, list)
        walkin_apps = [a for a in apps if (a.get("route") == "walkin")]
        assert len(walkin_apps) >= 5, \
            f"expected >=5 walkin apps, got {len(walkin_apps)}"
        # each companion row must have a synthetic job_id starting with 'walkin:'
        for a in walkin_apps[:5]:
            jid = a.get("job_id")
            assert isinstance(jid, str) and jid.startswith("walkin:"), \
                f"bad job_id on walkin app: {jid} in {a}"
        # distinct job_ids (dup-key fix invariant)
        jids = [a.get("job_id") for a in walkin_apps]
        assert len(set(jids)) == len(jids), f"dup walkin job_ids: {jids}"
