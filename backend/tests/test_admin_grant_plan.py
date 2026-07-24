"""Regression tests for the admin plan-grant endpoint.

Covers:
  * admin (only) may grant → 200 with granted=true + prior plan captured
  * repeat grant is idempotent → 200 with already_on_plan=true, granted=false
  * unknown plan → 400 with allowed enum
  * missing user → 404
  * support role is forbidden (403)
  * regular user is forbidden (403)

Uses the same preview conventions as `test_phase6_acceptance.py`: pytest hits
the running preview backend on REACT_APP_BACKEND_URL, seeds are already
present, and CI_TEST_ISSUER_ENABLED=true so login returns access_token.
"""
from __future__ import annotations
import os
import uuid
import pytest
import requests
from pathlib import Path
from pymongo import MongoClient

BASE = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://lynk-preview-2.preview.emergentagent.com",
).rstrip("/")

_BE_ENV: dict[str, str] = {}
_env_path = Path("/app/backend/.env")
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            _BE_ENV[k.strip()] = v.strip()
MONGO_URL = _BE_ENV.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = _BE_ENV.get("DB_NAME", "opportunityos")


def _login(email: str, password: str) -> tuple[str, requests.Session]:
    s = requests.Session()
    r = s.post(f"{BASE}/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"], s


def _bearer(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token():
    tok, _ = _login("admin@opportunityos.dev", "Admin!Console1")
    return tok


@pytest.fixture(scope="module")
def support_token():
    tok, _ = _login("support@opportunityos.dev", "Support!Console1")
    return tok


@pytest.fixture(scope="module")
def regular_token():
    tok, _ = _login("fixture-ead@opportunityos.dev", "Fixture!Test1")
    return tok


@pytest.fixture(scope="module")
def mongo_db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture
def a_fresh_user(mongo_db):
    """Create an ephemeral non-admin user directly in Mongo — no consent,
    no login. We only need its id for grant tests."""
    uid = str(uuid.uuid4())
    mongo_db.users.insert_one({
        "id": uid,
        "email": f"grant-target-{uid[:8]}@opportunityos.test",
        "password_hash": "",
        "name": "Grant Target",
        "passport_activated": False,
    })
    yield uid
    mongo_db.users.delete_one({"id": uid})
    mongo_db.subscriptions.delete_many({"user_id": uid})


class TestAdminGrantPlan:

    def test_admin_grants_plus_from_free(self, admin_token, a_fresh_user, mongo_db):
        r = requests.post(
            f"{BASE}/api/v1/admin/subscriptions/grant",
            headers=_bearer(admin_token),
            json={"user_id": a_fresh_user, "plan_slug": "plus", "note": "founder comp"},
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["granted"] is True
        assert b["already_on_plan"] is False
        assert b["plan"] == "plus"
        assert b["user_id"] == a_fresh_user
        assert b["subscription_id"]
        # DB reflects the plan
        sub = mongo_db.subscriptions.find_one({"user_id": a_fresh_user}, {"_id": 0})
        assert sub["plan"] == "plus"
        # Audit row was written
        audit_row = mongo_db.audit_logs.find_one(
            {"action": "admin.plan_granted", "object_ref": f"user:{a_fresh_user}"},
            {"_id": 0},
        )
        assert audit_row is not None
        assert audit_row["meta"]["plan"] == "plus"
        assert audit_row["meta"]["note"] == "founder comp"

    def test_repeat_grant_is_idempotent(self, admin_token, a_fresh_user, mongo_db):
        r1 = requests.post(
            f"{BASE}/api/v1/admin/subscriptions/grant",
            headers=_bearer(admin_token),
            json={"user_id": a_fresh_user, "plan_slug": "pro"},
        )
        assert r1.status_code == 200
        assert r1.json()["granted"] is True

        r2 = requests.post(
            f"{BASE}/api/v1/admin/subscriptions/grant",
            headers=_bearer(admin_token),
            json={"user_id": a_fresh_user, "plan_slug": "pro"},
        )
        assert r2.status_code == 200
        b2 = r2.json()
        assert b2["granted"] is False
        assert b2["already_on_plan"] is True
        assert b2["plan"] == "pro"
        # exactly ONE plan row remains (upsert did not duplicate)
        assert mongo_db.subscriptions.count_documents({"user_id": a_fresh_user}) == 1

    def test_unknown_plan_slug_rejected(self, admin_token, a_fresh_user):
        r = requests.post(
            f"{BASE}/api/v1/admin/subscriptions/grant",
            headers=_bearer(admin_token),
            json={"user_id": a_fresh_user, "plan_slug": "enterprise"},
        )
        assert r.status_code == 400
        det = r.json().get("detail", {})
        assert det.get("error") == "invalid_plan_slug"
        assert set(det.get("allowed", [])) == {"free", "plus", "pro", "max"}

    def test_missing_user_returns_404(self, admin_token):
        r = requests.post(
            f"{BASE}/api/v1/admin/subscriptions/grant",
            headers=_bearer(admin_token),
            json={"user_id": "user-that-does-not-exist", "plan_slug": "plus"},
        )
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "user_not_found"

    def test_support_role_forbidden(self, support_token, a_fresh_user):
        r = requests.post(
            f"{BASE}/api/v1/admin/subscriptions/grant",
            headers=_bearer(support_token),
            json={"user_id": a_fresh_user, "plan_slug": "plus"},
        )
        assert r.status_code == 403
        assert r.json()["detail"]["error"] == "admin_required"

    def test_regular_user_forbidden(self, regular_token, a_fresh_user):
        r = requests.post(
            f"{BASE}/api/v1/admin/subscriptions/grant",
            headers=_bearer(regular_token),
            json={"user_id": a_fresh_user, "plan_slug": "plus"},
        )
        assert r.status_code == 403
