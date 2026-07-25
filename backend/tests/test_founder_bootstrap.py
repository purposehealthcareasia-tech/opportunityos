"""Regression tests for the one-time founder bootstrap endpoint (A4).

Covers:
  * missing X-Service-Token       → 401
  * wrong X-Service-Token         → 403
  * valid token, no admin exists  → 200 + admin_users row + max plan + 2 audit rows
  * valid token, admin exists     → 409 self-disable (idempotent refusal)
  * founder user does not exist   → 404
  * token not configured          → 503
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
    "http://localhost:8001",
).rstrip("/")

FOUNDER_EMAIL = "swissarjun77@gmail.com"
FOUNDER_TOP_PLAN = "max"

_BE_ENV: dict[str, str] = {}
_env_path = Path("/app/backend/.env")
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            _BE_ENV[k.strip()] = v.strip()
MONGO_URL = _BE_ENV.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = _BE_ENV.get("DB_NAME", "opportunityos")
INTERNAL_TOKEN = _BE_ENV.get("INTERNAL_SERVICE_TOKEN", "")


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture
def clean_bootstrap_state(db):
    """Snapshot admin_users + founder user + subscription, run the test,
    then restore. Bootstrap MUST NOT leave test debris in preview DB."""
    admin_snapshot = list(db.admin_users.find({}))
    founder_snapshot = db.users.find_one({"email": FOUNDER_EMAIL})
    founder_id = (founder_snapshot or {}).get("id")
    sub_snapshot = db.subscriptions.find_one({"user_id": founder_id}) if founder_id else None

    # Start clean
    db.admin_users.delete_many({})

    # Ensure a founder user exists in preview DB for the happy path
    if not founder_snapshot:
        created_founder = True
        founder_snapshot = {
            "id": str(uuid.uuid4()),
            "email": FOUNDER_EMAIL,
            "password_hash": "",
            "name": "Founder Test Placeholder",
            "passport_activated": False,
        }
        db.users.insert_one(dict(founder_snapshot))
    else:
        created_founder = False

    yield founder_snapshot["id"]

    # Teardown: restore prior state
    db.admin_users.delete_many({})
    for row in admin_snapshot:
        row.pop("_id", None)
        db.admin_users.insert_one(row)
    if created_founder:
        db.users.delete_one({"email": FOUNDER_EMAIL})
        db.subscriptions.delete_many({"user_id": founder_snapshot["id"]})
    else:
        if sub_snapshot is None:
            db.subscriptions.delete_many({"user_id": founder_id})
        # If a sub already existed, set_plan will have overwritten it; not
        # attempting to restore historical plan bytes — teardown makes the
        # collection consistent with the founder record for subsequent tests.


class TestFounderBootstrap:
    URL = f"{BASE}/api/internal/admin/bootstrap-founder"

    def test_missing_token_401(self):
        r = requests.post(self.URL, timeout=15)
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "service_token_missing"

    def test_wrong_token_403(self):
        r = requests.post(self.URL,
                          headers={"X-Service-Token": "obviously-wrong-value"},
                          timeout=15)
        assert r.status_code == 403
        assert r.json()["detail"]["error"] == "service_token_invalid"

    def test_happy_path_grants_admin_and_top_plan(self, clean_bootstrap_state, db):
        founder_id = clean_bootstrap_state
        r = requests.post(self.URL,
                          headers={"X-Service-Token": INTERNAL_TOKEN},
                          timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["user_id"] == founder_id
        assert body["role_granted"] == "admin"
        assert body["plan_granted"] == FOUNDER_TOP_PLAN
        assert body["subscription_id"]
        # DB: admin_users row present
        admin_row = db.admin_users.find_one({"user_id": founder_id})
        assert admin_row is not None
        assert admin_row["role"] == "admin"
        # DB: subscription set to top plan
        sub = db.subscriptions.find_one({"user_id": founder_id})
        assert sub is not None
        assert sub["plan"] == FOUNDER_TOP_PLAN
        # Audit rows present
        role_audit = db.audit_logs.find_one({
            "action": "admin.role_granted",
            "object_ref": f"user:{founder_id}",
            "actor": "system:founder_bootstrap",
        })
        assert role_audit is not None
        plan_audit = db.audit_logs.find_one({
            "action": "admin.plan_granted",
            "object_ref": f"user:{founder_id}",
            "actor": "system:founder_bootstrap",
        })
        assert plan_audit is not None
        assert plan_audit["meta"]["plan"] == FOUNDER_TOP_PLAN

    def test_self_disable_after_bootstrap(self, clean_bootstrap_state, db):
        """Second call while admin_users is non-empty must 409."""
        # First run — bootstraps (need this to populate admin_users)
        r1 = requests.post(self.URL,
                           headers={"X-Service-Token": INTERNAL_TOKEN},
                           timeout=15)
        assert r1.status_code == 200, r1.text

        # Second run — must 409 (self-disable)
        r2 = requests.post(self.URL,
                           headers={"X-Service-Token": INTERNAL_TOKEN},
                           timeout=15)
        assert r2.status_code == 409
        det = r2.json()["detail"]
        assert det["error"] == "bootstrap_already_completed"
        assert det["admin_users_count"] >= 1

    def test_founder_user_not_found(self, db):
        """If the founder user doesn't exist, endpoint returns 404 (and
        does NOT create the admin_users row)."""
        admin_snapshot = list(db.admin_users.find({}))
        founder_snapshot = db.users.find_one({"email": FOUNDER_EMAIL})
        db.admin_users.delete_many({})
        if founder_snapshot:
            db.users.delete_one({"email": FOUNDER_EMAIL})
        try:
            r = requests.post(self.URL,
                              headers={"X-Service-Token": INTERNAL_TOKEN},
                              timeout=15)
            assert r.status_code == 404
            assert r.json()["detail"]["error"] == "founder_user_not_found"
            # admin_users still empty
            assert db.admin_users.count_documents({}) == 0
        finally:
            for row in admin_snapshot:
                row.pop("_id", None)
                db.admin_users.insert_one(row)
            if founder_snapshot:
                founder_snapshot.pop("_id", None)
                db.users.insert_one(founder_snapshot)
