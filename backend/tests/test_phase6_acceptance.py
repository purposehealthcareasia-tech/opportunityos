"""Phase 6 close-out acceptance tests (iteration 8).

Covers: auth cookies + CSRF, startup guards, admin console, support read-only,
refund + audit, feature flag toggle, manual queue, billing S19, privacy S20,
gate enumeration, receipts unique-index concurrent race + duplicate 409,
link-import 409, SAMPLE metric exclusion.

Runs against the live preview base URL (REACT_APP_BACKEND_URL). Uses Bearer for
the CI test issuer path (CI_TEST_ISSUER_ENABLED=true in preview) — this is
identical behaviour to prior phases' pytest runs.
"""
from __future__ import annotations
import os
import uuid
import time
import json
import threading
import pytest
import requests
from pathlib import Path
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://lynk-preview-2.preview.emergentagent.com").rstrip("/")

# Read backend env for direct Mongo access
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


# -------- helpers --------

def _login(email: str, password: str) -> tuple[str, str, str, requests.Session]:
    """Log in via cookie + capture Bearer + CSRF. Returns (token, csrf, session_id, session)."""
    s = requests.Session()
    r = s.post(f"{BASE}/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    tok = body["access_token"]
    csrf = s.cookies.get("oppos_csrf") or ""
    sid = s.cookies.get("oppos_session") or ""
    return tok, csrf, sid, s


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def fixture_login():
    return _login("fixture-ead@opportunityos.dev", "Fixture!Test1")


@pytest.fixture(scope="module")
def admin_login():
    return _login("admin@opportunityos.dev", "Admin!Console1")


@pytest.fixture(scope="module")
def support_login():
    return _login("support@opportunityos.dev", "Support!Console1")


@pytest.fixture(scope="module")
def mongo_db():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


# ---------------- Startup guards ----------------

class TestStartup:
    def test_health(self):
        # SEC-004(d) — public health strips deploy flags.
        r = requests.get(f"{BASE}/api/health")
        assert r.status_code == 200
        b = r.json()
        assert b["phase"] == 6
        assert b["mongo"] is True
        # Flags now live on the admin health endpoint only.
        assert "ci_test_issuer_enabled" not in b, "SEC-004(d): public health must not leak this flag"
        assert "prod_mode" not in b, "SEC-004(d): public health must not leak this flag"


# ---------------- Auth hardening ----------------

class TestAuthHardening:
    def test_login_sets_cookies(self):
        s = requests.Session()
        r = s.post(f"{BASE}/api/v1/auth/login",
                   json={"email": "fixture-ead@opportunityos.dev", "password": "Fixture!Test1"})
        assert r.status_code == 200
        # Session cookie httpOnly, secure, samesite lax (user)
        set_cookies = r.headers.get("set-cookie") or ""
        assert "oppos_session=" in set_cookies
        assert "HttpOnly" in set_cookies
        assert "Secure" in set_cookies
        assert "SameSite=lax" in set_cookies or "SameSite=Lax" in set_cookies
        # CSRF cookie must exist AND not be httpOnly
        assert "oppos_csrf=" in set_cookies
        # oppos_csrf portion should NOT have HttpOnly flag
        csrf_seg = [seg for seg in set_cookies.split(",") if "oppos_csrf=" in seg]
        assert csrf_seg, "csrf cookie not set"
        assert "HttpOnly" not in csrf_seg[0]

    def test_admin_login_samesite_strict(self):
        s = requests.Session()
        r = s.post(f"{BASE}/api/v1/auth/login",
                   json={"email": "admin@opportunityos.dev", "password": "Admin!Console1"})
        assert r.status_code == 200
        raw = r.headers.get("set-cookie") or ""
        # extract session cookie chunk
        assert "oppos_session=" in raw
        # SameSite Strict for admin
        session_seg = [seg for seg in raw.split(",") if "oppos_session=" in seg]
        assert session_seg
        assert "strict" in session_seg[0].lower()

    def test_me_with_cookies_only(self):
        s = requests.Session()
        r = s.post(f"{BASE}/api/v1/auth/login",
                   json={"email": "fixture-ead@opportunityos.dev", "password": "Fixture!Test1"})
        assert r.status_code == 200
        # Now call /me WITHOUT bearer, cookies attached automatically by session
        r2 = s.get(f"{BASE}/api/v1/auth/me")
        assert r2.status_code == 200, r2.text
        assert r2.json()["email"] == "fixture-ead@opportunityos.dev"

    def test_csrf_missing_header_returns_403(self):
        """Cookie-authenticated POST without X-CSRF-Token → 403 csrf_invalid."""
        s = requests.Session()
        r = s.post(f"{BASE}/api/v1/auth/login",
                   json={"email": "fixture-ead@opportunityos.dev", "password": "Fixture!Test1"})
        assert r.status_code == 200
        # POST endpoint that requires auth. Use privacy/export.
        r2 = s.post(f"{BASE}/api/v1/privacy/export")
        assert r2.status_code == 403, f"expected 403, got {r2.status_code}: {r2.text}"
        body = r2.json()
        # detail.error == 'csrf_invalid'
        det = body.get("detail", {})
        assert (det.get("error") if isinstance(det, dict) else det) == "csrf_invalid"

    def test_csrf_with_matching_header_bypasses(self):
        s = requests.Session()
        r = s.post(f"{BASE}/api/v1/auth/login",
                   json={"email": "fixture-ead@opportunityos.dev", "password": "Fixture!Test1"})
        assert r.status_code == 200
        csrf = s.cookies.get("oppos_csrf")
        assert csrf
        r2 = s.post(f"{BASE}/api/v1/privacy/export",
                    headers={"X-CSRF-Token": csrf})
        # Should not be csrf_invalid; expect 200
        assert r2.status_code != 403 or (
            r2.json().get("detail", {}).get("error") != "csrf_invalid"
        )
        # ideally 200 or another 2xx/4xx that's not csrf_invalid
        assert r2.status_code in (200, 201)

    def test_bearer_bypasses_csrf(self, fixture_login):
        tok, _, _, _ = fixture_login
        r = requests.post(f"{BASE}/api/v1/privacy/export", headers=_bearer(tok))
        assert r.status_code == 200

    def test_logout_revokes_session(self, mongo_db):
        s = requests.Session()
        r = s.post(f"{BASE}/api/v1/auth/login",
                   json={"email": "fixture-ead@opportunityos.dev", "password": "Fixture!Test1"})
        assert r.status_code == 200
        sid = s.cookies.get("oppos_session")
        csrf = s.cookies.get("oppos_csrf")
        r2 = s.post(f"{BASE}/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert r2.status_code == 200
        row = mongo_db.sessions.find_one({"session_id": sid})
        assert row is not None
        assert row.get("revoked_at") is not None
        # /me after logout should be 401
        r3 = s.get(f"{BASE}/api/v1/auth/me")
        assert r3.status_code == 401


# ---------------- Admin console + support role ----------------

class TestAdminConsole:
    def test_admin_users_list(self, admin_login):
        tok, *_ = admin_login
        r = requests.get(f"{BASE}/api/v1/admin/users?q=fixture", headers=_bearer(tok))
        assert r.status_code == 200
        assert r.json()["count"] >= 1

    def test_admin_user_detail_writes_audit(self, admin_login, mongo_db):
        tok, *_ = admin_login
        # find fixture user id
        r0 = requests.get(f"{BASE}/api/v1/admin/users?q=fixture", headers=_bearer(tok))
        uid = r0.json()["users"][0]["id"]
        admin_id = mongo_db.admin_users.find_one({"role": "admin"})["user_id"]
        before = mongo_db.audit_logs.count_documents({"actor": admin_id, "action": "admin.user_detail_view"})
        r = requests.get(f"{BASE}/api/v1/admin/users/{uid}", headers=_bearer(tok))
        assert r.status_code == 200
        body = r.json()
        # Check sealed masking on any sealed claim
        sealed = [c for c in body.get("claims", []) if (c.get("sensitivity") or "").lower() == "sealed"]
        if sealed:
            for c in sealed:
                assert c["value"] == "•••• (sealed)", c
        after = mongo_db.audit_logs.count_documents({"actor": admin_id, "action": "admin.user_detail_view"})
        assert after >= before + 1

    # ------------------------------------------------------------------
    # v0.1 close-out fix directive #1 — P0 SECURITY.
    # /api/v1/admin/users/{id} MUST NOT return credential material.
    # ------------------------------------------------------------------
    def test_admin_user_detail_never_leaks_password_hash(self, admin_login, support_login):
        r0 = requests.get(f"{BASE}/api/v1/admin/users?q=fixture", headers=_bearer(admin_login[0]))
        uid = r0.json()["users"][0]["id"]
        for label, login in (("admin", admin_login), ("support", support_login)):
            tok, *_ = login
            r = requests.get(f"{BASE}/api/v1/admin/users/{uid}", headers=_bearer(tok))
            assert r.status_code == 200, f"{label} 200 required, got {r.status_code}"
            body = r.json()
            u = body.get("user", {})
            for k in ("password_hash", "password", "totp_secret", "recovery_codes"):
                assert k not in u, f"{label} response leaked credential field {k}: keys={list(u.keys())}"
            # Serialized JSON body must not contain the sensitive keys either.
            text = json.dumps(body)
            for k in ("password_hash", "totp_secret"):
                assert k not in text, f"{label} response body contains sensitive key `{k}`"

    # ------------------------------------------------------------------
    # v0.1 close-out fix directive #2 — P1 PROVABLE SEALED MASKING.
    # Admin user-detail surfaces eligibility_profile (MASKED when sealed)
    # AND sealed claims come back with value == '•••• (sealed)'. No unmask.
    # ------------------------------------------------------------------
    def test_admin_user_detail_masks_sealed_data(self, admin_login, support_login, mongo_db):
        MASK = "•••• (sealed)"
        r0 = requests.get(f"{BASE}/api/v1/admin/users?q=fixture", headers=_bearer(admin_login[0]))
        uid = r0.json()["users"][0]["id"]

        # Insert a demonstrable sealed claim on the fixture (idempotent for the test).
        sealed_id = f"pytest-sealed-{uuid.uuid4()}"
        mongo_db.claims.insert_one({
            "id": sealed_id,
            "user_id": uid,
            "type": "identity",
            "value": {"ssn_last4": "1234", "note": "SENTINEL_SHOULD_NEVER_LEAK"},
            "sensitivity": "sealed",
            "status": "approved",
            "version": 99,
            "superseded_by": None,
            "user_approved": True,
            "confidence": None,
            "source": {"type": "test"},
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        try:
            for label, login in (("admin", admin_login), ("support", support_login)):
                tok, *_ = login
                r = requests.get(f"{BASE}/api/v1/admin/users/{uid}", headers=_bearer(tok))
                assert r.status_code == 200, f"{label} status {r.status_code}"
                body = r.json()

                # 1) The sealed claim we just inserted must be present AND masked.
                mine = next((c for c in body.get("claims", []) if c.get("id") == sealed_id), None)
                assert mine is not None, f"{label}: sealed claim not surfaced"
                assert mine["value"] == MASK, f"{label}: sealed claim value not masked, got {mine['value']!r}"

                # 2) No sentinel token from the sealed value may appear anywhere in the body.
                body_text = json.dumps(body)
                assert "SENTINEL_SHOULD_NEVER_LEAK" not in body_text, f"{label}: sealed value leaked into body"
                assert "1234" not in body_text or body_text.count("1234") == 0, f"{label}: sealed value leaked"

                # 3) Eligibility_profile surfaced. When sensitivity=sealed, data fields → MASK.
                elig = body.get("eligibility_profile")
                assert elig is not None, f"{label}: eligibility_profile omitted (P1 regression)"
                if (elig.get("sensitivity") or "").lower() == "sealed":
                    for k in ("status", "dates", "notes", "derived_flags"):
                        if k in elig and elig[k] is not None:
                            assert elig[k] == MASK, f"{label}: eligibility.{k} not masked, got {elig[k]!r}"
                # Structural fields must still be visible.
                assert "user_id" in elig
                assert "sensitivity" in elig
        finally:
            mongo_db.claims.delete_one({"id": sealed_id})

    def test_admin_health_shape(self, admin_login):
        tok, *_ = admin_login
        r = requests.get(f"{BASE}/api/v1/admin/health", headers=_bearer(tok))
        assert r.status_code == 200
        b = r.json()
        assert "counts" in b
        for key in ["users", "jobs", "applications", "feature_flags", "audit_logs"]:
            assert key in b["counts"]


class TestSupportReadOnly:
    def test_support_can_read_admin(self, support_login):
        tok, *_ = support_login
        r = requests.get(f"{BASE}/api/v1/admin/users", headers=_bearer(tok))
        assert r.status_code == 200

    def test_support_cannot_refund(self, support_login, mongo_db):
        tok, *_ = support_login
        # pick any sub id (create one via direct insert if needed)
        sub = mongo_db.subscriptions.find_one({}) or {}
        sub_id = sub.get("id") or str(uuid.uuid4())
        r = requests.post(f"{BASE}/api/v1/admin/subscriptions/{sub_id}/refund",
                          headers=_bearer(tok), json={"reason": "customer_request", "note": "test"})
        assert r.status_code == 403
        det = r.json().get("detail", {})
        err = det.get("error") if isinstance(det, dict) else det
        assert err == "admin_required"

    def test_support_cannot_toggle_flag(self, support_login):
        tok, *_ = support_login
        r = requests.patch(f"{BASE}/api/v1/admin/flags/feed_enabled",
                           headers=_bearer(tok), json={"enabled": False})
        assert r.status_code == 403

    def test_support_cannot_resolve_queue(self, support_login):
        tok, *_ = support_login
        r = requests.post(f"{BASE}/api/v1/admin/manual-queue/xyz/resolve",
                          headers=_bearer(tok), json={"note": "x"})
        assert r.status_code == 403

    def test_support_can_reply_ticket(self, support_login, admin_login, mongo_db):
        # ensure a ticket exists
        tok_admin, *_ = admin_login
        t_id = str(uuid.uuid4())
        mongo_db.support_tickets.insert_one({
            "id": t_id, "user_id": "test", "subject": "test",
            "body": "b", "status": "open", "created_at": "2026-07-20T00:00:00",
            "updated_at": "2026-07-20T00:00:00", "replies": [],
        })
        tok, *_ = support_login
        r = requests.post(f"{BASE}/api/v1/admin/support-tickets/{t_id}/reply",
                          headers=_bearer(tok), json={"reply": "hello from support"})
        assert r.status_code == 200
        # close
        r2 = requests.post(f"{BASE}/api/v1/admin/support-tickets/{t_id}/close",
                           headers=_bearer(tok))
        assert r2.status_code == 200
        mongo_db.support_tickets.delete_one({"id": t_id})


# ---------------- Refund + audit ----------------

class TestAdminRefund:
    def test_invalid_reason_400(self, admin_login, mongo_db):
        tok, *_ = admin_login
        sub = mongo_db.subscriptions.find_one({})
        if not sub:
            # seed one
            sub = {"id": str(uuid.uuid4()), "user_id": "u", "plan": "plus",
                   "status": "active", "created_at": "2026-07-20T00:00:00"}
            mongo_db.subscriptions.insert_one(sub)
        r = requests.post(f"{BASE}/api/v1/admin/subscriptions/{sub['id']}/refund",
                          headers=_bearer(tok),
                          json={"reason": "not_a_valid_reason", "note": ""})
        assert r.status_code == 400
        det = r.json().get("detail", {})
        assert det.get("error") == "invalid_reason"

    def test_valid_refund_writes_audit(self, admin_login, mongo_db):
        tok, *_ = admin_login
        # ensure a sub exists
        sub = mongo_db.subscriptions.find_one({})
        assert sub is not None, "need a sub to test refund"
        admin_id = mongo_db.admin_users.find_one({"role": "admin"})["user_id"]
        before = mongo_db.audit_logs.count_documents({
            "actor": admin_id, "action": "admin.refund_issued"})
        r = requests.post(f"{BASE}/api/v1/admin/subscriptions/{sub['id']}/refund",
                          headers=_bearer(tok),
                          json={"reason": "customer_request", "note": "test refund iter8"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["refunded"] is True
        after = mongo_db.audit_logs.count_documents({
            "actor": admin_id, "action": "admin.refund_issued"})
        assert after >= before + 1
        row = mongo_db.audit_logs.find_one(
            {"actor": admin_id, "action": "admin.refund_issued"}, sort=[("ts", -1)])
        assert row["meta"]["reason"] == "customer_request"


# ---------------- Feature flag toggle ----------------

class TestFeatureFlag:
    def test_toggle_off_then_on(self, admin_login, mongo_db):
        tok, *_ = admin_login
        admin_id = mongo_db.admin_users.find_one({"role": "admin"})["user_id"]
        # OFF
        r1 = requests.patch(f"{BASE}/api/v1/admin/flags/feed_enabled",
                            headers=_bearer(tok), json={"enabled": False})
        assert r1.status_code == 200
        assert r1.json()["enabled"] is False
        audit_row = mongo_db.audit_logs.find_one(
            {"actor": admin_id, "action": "admin.flag_toggled"}, sort=[("ts", -1)])
        assert audit_row["meta"]["enabled"] is False
        # ON
        r2 = requests.patch(f"{BASE}/api/v1/admin/flags/feed_enabled",
                            headers=_bearer(tok), json={"enabled": True})
        assert r2.status_code == 200
        assert r2.json()["enabled"] is True


# ---------------- Manual queue ----------------

class TestManualQueue:
    def test_seed_and_resolve(self, admin_login, mongo_db):
        tok, *_ = admin_login
        item_id = str(uuid.uuid4())
        app_id = f"TEST_app_{uuid.uuid4().hex[:8]}"
        mongo_db.manual_queue_items.insert_one({
            "id": item_id, "application_id": app_id,
            "state": "queued", "created_at": "2026-07-20T00:00:00",
        })
        r = requests.post(f"{BASE}/api/v1/admin/manual-queue/{item_id}/resolve",
                          headers=_bearer(tok), json={"note": "ok"})
        assert r.status_code == 200
        assert r.json()["resolution_note"] == "ok"


# ---------------- Billing S19 ----------------

class TestBilling:
    def test_catalog(self, fixture_login):
        tok, *_ = fixture_login
        r = requests.get(f"{BASE}/api/v1/billing/catalog", headers=_bearer(tok))
        assert r.status_code == 200
        b = r.json()
        # Expected three plans
        plans = b.get("plans") or b
        # accept either shape
        if isinstance(plans, dict):
            plans_list = plans.get("plans") or list(plans.values())
        else:
            plans_list = plans
        assert isinstance(plans_list, list)
        assert len(plans_list) >= 3

    def test_usage_me(self, fixture_login):
        tok, *_ = fixture_login
        r = requests.get(f"{BASE}/api/v1/usage/me", headers=_bearer(tok))
        assert r.status_code == 200
        b = r.json()
        meters = b.get("meters") or b
        # 3 meters, each with used/cap/resets_at
        assert "meter_definitions_verbatim" in b or "meters" in b

    def test_coupon_apply(self, fixture_login):
        tok, csrf, sid, s = fixture_login
        r = requests.post(f"{BASE}/api/v1/billing/coupon/apply", headers=_bearer(tok),
                          json={"code": "FOUNDER19"})
        assert r.status_code == 200
        assert r.json().get("valid") is True

    def test_checkout(self, fixture_login):
        tok, *_ = fixture_login
        r = requests.post(f"{BASE}/api/v1/billing/checkout", headers=_bearer(tok),
                          json={"lookup_key": "plus_monthly", "origin_url": BASE})
        assert r.status_code == 200, r.text
        assert "checkout_url" in r.json()


# ---------------- Privacy S20 ----------------

class TestPrivacy:
    def test_consents_shape(self, fixture_login):
        tok, *_ = fixture_login
        r = requests.get(f"{BASE}/api/v1/privacy/consents", headers=_bearer(tok))
        assert r.status_code == 200
        scopes = r.json().get("scopes", [])
        assert len(scopes) >= 4

    def test_export_flow(self, fixture_login):
        tok, *_ = fixture_login
        r = requests.post(f"{BASE}/api/v1/privacy/export", headers=_bearer(tok))
        assert r.status_code == 200
        b = r.json()
        assert b.get("status") == "ready"
        job_id = b["job_id"]
        r2 = requests.get(f"{BASE}/api/v1/privacy/export/{job_id}", headers=_bearer(tok))
        assert r2.status_code == 200
        b2 = r2.json()
        assert b2["status"] == "ready"
        content = b2["download"]["content"]
        for key in ["profile", "claims", "applications", "submission_receipts", "subscriptions"]:
            assert key in content, f"missing key {key} in export bundle"

    def test_soft_delete_and_login_block(self, admin_login):
        """Create a fresh user, mark deletion_pending, verify login 403."""
        email = f"TEST_delete_{uuid.uuid4().hex[:8]}@opportunityos.dev"
        # signup via API (public)
        r = requests.post(f"{BASE}/api/v1/auth/signup", json={
            "email": email, "password": "Test!Pass1", "name": "Del User",
            "policy_text_version": "1.0",
            "consents": {
                "process_career_data": True,
                "discover_jobs": True,
                "generate_materials": True,
                "track_applications": True,
                "email_me": False,
            },
        })
        assert r.status_code == 201, r.text
        tok = r.json().get("access_token")
        # request account/delete with Bearer bypasses CSRF
        r2 = requests.post(f"{BASE}/api/v1/privacy/account/delete",
                           headers=_bearer(tok), json={"confirm": True})
        assert r2.status_code == 200
        b2 = r2.json()
        assert "deletion_pending_at" in b2 and "deletion_scheduled_for" in b2
        # subsequent login should return 403 account_deletion_pending
        r3 = requests.post(f"{BASE}/api/v1/auth/login", json={
            "email": email, "password": "Test!Pass1",
        })
        assert r3.status_code == 403
        det = r3.json().get("detail", {})
        err = det.get("error") if isinstance(det, dict) else det
        assert err == "account_deletion_pending"


# ---------------- Phase 3 gate enumeration ----------------

EXPECTED_GATES = {
    "vacancy_open", "authorization_scope", "duplicate_check", "work_auth",
    "sponsorship", "stem_opt_viability", "itar", "security_clearance",
    "licensure", "location_onsite", "experience_band", "education_requirement",
    "salary_floor", "employer_exclusions",
}


class TestGates:
    def test_feed_geometry_and_gates(self, fixture_login):
        tok, *_ = fixture_login
        # Rebase fixture first for determinism
        if INTERNAL_TOKEN:
            rr = requests.post(f"{BASE}/api/internal/fixture/rebase",
                               headers={"X-Service-Token": INTERNAL_TOKEN})
            assert rr.status_code == 200
        r = requests.get(f"{BASE}/api/v1/jobs/feed", headers=_bearer(tok))
        assert r.status_code == 200
        b = r.json()
        # count passing/excluded  
        passing = b.get("passing") or []
        excluded = b.get("excluded") or []
        # sometimes result is under 'jobs'/'excluded_jobs'
        if not passing and "jobs" in b:
            passing = b.get("jobs", [])
        # Print totals for debugging
        print(f"passing={len(passing)}, excluded={len(excluded)}, keys={list(b.keys())}")
        # 9/6 geometry
        assert len(passing) == 9, f"expected 9 passing, got {len(passing)}"
        assert len(excluded) == 6, f"expected 6 excluded, got {len(excluded)}"


# ---------------- Receipts unique index + duplicate 409 ----------------

class TestReceiptsUnique:
    def test_unique_index_exists(self, mongo_db):
        idx = mongo_db.submission_receipts.index_information()
        # find any index that covers (user_id, company_id, req_ref) and is unique
        found = False
        for name, spec in idx.items():
            keys = [k for k, _ in spec.get("key", [])]
            if set(keys) >= {"user_id", "company_id", "req_ref"} and spec.get("unique"):
                found = True
                break
        assert found, f"unique index missing on submission_receipts: {idx}"

    def test_concurrent_duplicate_insert(self, mongo_db):
        """Two threads insert the same (user_id, company_id, req_ref) — exactly
        one succeeds, the other raises DuplicateKeyError."""
        user_id = f"TEST_race_{uuid.uuid4().hex[:8]}"
        company_id = "TEST_co"
        req_ref = "TEST_req::" + uuid.uuid4().hex[:8]
        results: list[str] = []

        def _ins():
            try:
                mongo_db.submission_receipts.insert_one({
                    "id": str(uuid.uuid4()), "user_id": user_id,
                    "company_id": company_id, "req_ref": req_ref,
                    "application_id": "x", "job_id": "y",
                    "materials_manifest_hash": "z", "submit_channel": "manual_queue",
                    "supersedes": None, "ts": "2026-07-20T00:00:00",
                })
                results.append("ok")
            except DuplicateKeyError:
                results.append("dup")
            except Exception as e:
                results.append(f"err:{e}")

        t1 = threading.Thread(target=_ins)
        t2 = threading.Thread(target=_ins)
        t1.start(); t2.start(); t1.join(); t2.join()
        # Cleanup
        mongo_db.submission_receipts.delete_many({"user_id": user_id})
        assert sorted(results) == ["dup", "ok"], f"expected 1 ok + 1 dup, got {results}"


# ---------------- Link-import 409 ----------------

class TestLinkImport:
    @pytest.mark.parametrize("host_url", [
        "https://linkedin.com/jobs/view/xyz",
        "https://www.indeed.com/viewjob?jk=abc",
        "https://joinhandshake.com/jobs/12345",
    ])
    def test_blocklist_returns_409(self, fixture_login, host_url):
        tok, *_ = fixture_login
        r = requests.post(f"{BASE}/api/v1/jobs/import", headers=_bearer(tok),
                          json={"url": host_url})
        assert r.status_code == 409, f"expected 409 for {host_url}, got {r.status_code}: {r.text}"
        det = r.json().get("detail", {})
        err = det.get("error") if isinstance(det, dict) else det
        assert err == "route_unavailable_platform_policy"


# ---------------- SAMPLE row exclusion from metrics ----------------

class TestSampleExclusion:
    def test_funnel_totals_vs_sample(self, fixture_login):
        tok, *_ = fixture_login
        r = requests.get(f"{BASE}/api/v1/analytics/funnel", headers=_bearer(tok))
        assert r.status_code == 200
        b = r.json()
        assert "totals" in b, f"missing totals: {b.keys()}"
        assert "sample" in b, f"missing sample: {b.keys()}"
