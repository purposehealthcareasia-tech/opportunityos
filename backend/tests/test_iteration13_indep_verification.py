"""Iteration 13 — INDEPENDENT verification of milestones B–H against the
live preview backend (no code introspection — pure HTTP contract tests).

This file is written from the review-request perspective: hit the public
preview URL for every checkpoint and assert the exact HTTP semantics that
milestones B → H must guarantee.
"""
from __future__ import annotations

import io
import json
import os
import time
import uuid

import pytest
import requests


BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    # Fallback to /app/frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE = line.strip().split("=", 1)[1].rstrip("/")
                    break
    except Exception:
        pass
assert BASE, "REACT_APP_BACKEND_URL must be resolvable for iteration 13 tests"

EXPECTED_HOST = "lynk-preview-2.preview.emergentagent.com"

# --- credentials from /app/memory/test_credentials.md ---
FIXTURE_EMAIL = "fixture-ead@opportunityos.dev"
FIXTURE_PASSWORD = "Fixture!Test1"
ADMIN_EMAIL = "admin@opportunityos.dev"
ADMIN_PASSWORD = "Admin!Console1"
SUPPORT_EMAIL = "support@opportunityos.dev"
SUPPORT_PASSWORD = "Support!Console1"


# ---------------------------------------------------------------------------
# Login helpers (Bearer JWT path — CI_TEST_ISSUER_ENABLED=true)
# ---------------------------------------------------------------------------
def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{BASE}/api/v1/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    tok = r.json().get("access_token")
    assert tok, f"login for {email} returned no access_token"
    return tok


@pytest.fixture(scope="module")
def fixture_token() -> str:
    return _login(FIXTURE_EMAIL, FIXTURE_PASSWORD)


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def support_token() -> str:
    return _login(SUPPORT_EMAIL, SUPPORT_PASSWORD)


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ===========================================================================
# MILESTONE B — Emergent object storage
# ===========================================================================
class TestMilestoneB_Storage:
    def test_admin_media_storage_status_ok(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/media_storage",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Preview has EMERGENT_LLM_KEY → status TEST_MODE (or CONNECTED per spec).
        assert body["status"] in ("TEST_MODE", "CONNECTED"), body
        assert body["slug"] == "media_storage"
        assert body["category"] == "storage"

    def test_admin_media_storage_test_connection(self, admin_token):
        r = requests.post(
            f"{BASE}/api/v1/admin/integrations/media_storage/test",
            headers=_auth(admin_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True, body

    def test_document_upload_reaches_emergent_backend(self, fixture_token):
        """Actual live endpoint is POST /api/v1/documents/resume (PDF/DOCX only).
        We upload a minimal valid PDF and verify the document row is created;
        the storage engine (`backend='emergent'`) is proved by the
        MediaStorageProvider `test_connection` above + the unit tests in
        /app/backend/tests/test_milestone_b_storage.py."""
        # Minimal well-formed PDF (~180 bytes) accepted by the parser stub.
        pdf = (
            b"%PDF-1.4\n"
            b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
            b"2 0 obj <</Type /Pages /Kids [] /Count 0>> endobj\n"
            b"xref\n0 3\n0000000000 65535 f\n"
            b"0000000009 00000 n\n0000000053 00000 n\n"
            b"trailer <</Size 3 /Root 1 0 R>>\nstartxref\n104\n%%EOF\n"
        )
        # Make the payload unique so the sha dedup path always hits the
        # storage backend at least once.
        pdf += b"\n%iter13-" + uuid.uuid4().hex.encode() + b"\n"
        files = {"file": ("iter13.pdf", io.BytesIO(pdf), "application/pdf")}
        r = requests.post(
            f"{BASE}/api/v1/documents/resume",
            headers=_auth(fixture_token),
            files=files, timeout=60,
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        doc = body.get("document", body)
        # `_to_response()` intentionally strips `s3_key` from the API surface —
        # sha256 + size_bytes are the observable proof the file went through
        # the storage backend. Backend selection is proved by
        # `test_milestone_b_storage.py::test_backend_selected_matches_env`.
        assert doc.get("id"), body
        assert doc.get("sha256"), body
        assert doc.get("size_bytes") == len(pdf), body

        # Verify listing surfaces the doc back.
        r2 = requests.get(f"{BASE}/api/v1/documents/me",
                            headers=_auth(fixture_token), timeout=20)
        assert r2.status_code == 200, r2.text
        ids = [d["id"] for d in r2.json().get("documents", [])]
        assert doc["id"] in ids, "uploaded doc not visible in /documents/me"


# ===========================================================================
# MILESTONE C — Email adapters (Resend + SendGrid)
# ===========================================================================
class TestMilestoneC_Email:
    def test_resend_admin_detail_shape(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/resend",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["category"] == "email"
        assert body["status"] == "CONFIGURATION_REQUIRED"
        # webhook_url should be present and end with the expected path.
        wh = body.get("webhook_url", "")
        assert wh.endswith("/api/webhook/email/resend"), body

    def test_sendgrid_admin_detail_shape(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/sendgrid",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["category"] == "email"
        wh = body.get("webhook_url", "")
        assert wh.endswith("/api/webhook/email/sendgrid"), body

    def test_resend_webhook_hardfail_503_no_secret(self):
        r = requests.post(
            f"{BASE}/api/webhook/email/resend",
            data=b'{"random":"body"}',
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        # 503 = "the operator has not finished configuring this provider on
        # the server". This is the missing-secret contract; never a 2xx or 500.
        assert r.status_code == 503, r.text
        j = r.json()
        detail = j.get("detail", {})
        assert isinstance(detail, dict), j
        assert "webhook_secret_not_configured" in json.dumps(detail), j

    def test_sendgrid_webhook_hardfail_no_signature(self):
        r = requests.post(
            f"{BASE}/api/webhook/email/sendgrid",
            data=b"[]",
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        # Missing verification key on the server → 503.
        # Missing headers with a configured key → 400.
        # Never a 2xx.
        assert r.status_code in (400, 503), r.text
        j = r.json()
        assert "webhook_verification_failed" in json.dumps(j), j

    def test_unknown_email_provider_returns_404(self):
        r = requests.post(
            f"{BASE}/api/webhook/email/mailgun",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        assert r.status_code == 404, r.text
        j = r.json()
        assert "unknown_email_provider" in json.dumps(j), j


# ===========================================================================
# MILESTONE D — Twilio Verify adapter
# ===========================================================================
class TestMilestoneD_Twilio:
    def test_twilio_admin_detail_configuration_required(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/twilio",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "CONFIGURATION_REQUIRED"
        missing = set(body.get("missing_env", []))
        for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                   "TWILIO_VERIFY_SERVICE_SID"):
            assert k in missing, body
        # Never leaks values (there are none set anyway) — just assert body
        # does not surface any 'value' field with real content.
        body_repr = json.dumps(body)
        assert '"AC' not in body_repr, body_repr  # Twilio SIDs start with AC


# ===========================================================================
# MILESTONE E — Google Sign-In backend
# ===========================================================================
class TestMilestoneE_GoogleBackend:
    def test_invalid_google_session_returns_401(self):
        r = requests.post(
            f"{BASE}/api/v1/auth/google/session",
            json={"session_id": "bogus-" + uuid.uuid4().hex},
            timeout=30,
        )
        # Must be 401 with google_session_invalid — never a 502 bad-gateway.
        assert r.status_code == 401, f"expected 401 got {r.status_code}: {r.text}"
        assert "google_session_invalid" in json.dumps(r.json()), r.json()

    def test_google_session_route_is_csrf_exempt(self):
        # Setting a bogus csrf cookie without matching header must NOT block
        # this route (i.e. it should still respond with 401 from the service
        # logic, not with a 403 csrf_verification_failed).
        r = requests.post(
            f"{BASE}/api/v1/auth/google/session",
            json={"session_id": "bogus"},
            headers={"Cookie": "oppos_csrf=abc"},
            timeout=30,
        )
        assert r.status_code == 401, r.text
        assert "csrf" not in r.text.lower() or "google_session_invalid" in r.text

    def test_complete_signup_unknown_pending_returns_404(self):
        r = requests.post(
            f"{BASE}/api/v1/auth/google/complete",
            json={
                "pending_signup_id": "does-not-exist-" + uuid.uuid4().hex,
                "consents": {
                    "process_career_data": True, "discover_jobs": True,
                    "generate_materials": False, "track_applications": False,
                    "email_me": False,
                },
                "policy_text_version": "1.0",
            },
            timeout=20,
        )
        assert r.status_code == 404, r.text
        assert "pending_signup_not_found" in json.dumps(r.json()), r.json()

    def test_google_auth_provider_status(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/google_auth",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Emergent-managed: CONNECTED (per review request) OR TEST_MODE per registry.
        assert body["status"] in ("CONNECTED", "TEST_MODE"), body


# ===========================================================================
# MILESTONE F — Payments (Stripe / Razorpay / webhooks)
# ===========================================================================
class TestMilestoneF_Payments:
    def test_stripe_admin_detail(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/stripe",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "TEST_MODE", body
        wh = body.get("webhook_url", "")
        assert wh.endswith("/api/webhook/payment/stripe"), body

    def test_stripe_webhook_url_uses_preview_host(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/stripe",
            headers=_auth(admin_token), timeout=20,
        )
        wh = r.json().get("webhook_url", "")
        # Host must be the preview host, not a raw cluster domain (svc.cluster.local etc).
        assert EXPECTED_HOST in wh, f"webhook_url host must be preview host: {wh!r}"

    def test_razorpay_admin_detail_configuration_required(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/razorpay",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "CONFIGURATION_REQUIRED"
        missing = set(body.get("missing_env", []))
        assert "RAZORPAY_KEY_ID" in missing and "RAZORPAY_KEY_SECRET" in missing, body

    def test_stripe_webhook_hardfails_400_or_503(self):
        r = requests.post(
            f"{BASE}/api/webhook/payment/stripe",
            data=b'{"random":"payload"}',
            headers={"Content-Type": "application/json",
                      "Stripe-Signature": f"t={int(time.time())},v1=deadbeef"},
            timeout=20,
        )
        # Semantic contract:
        #   - 400 = vendor sent a payload with an invalid signature.
        #   - 503 = STRIPE_WEBHOOK_SECRET not configured on this server.
        # Never a 2xx or a 500.
        assert r.status_code in (400, 503), r.text
        assert "webhook_verification_failed" in json.dumps(r.json()), r.json()

    def test_razorpay_webhook_hardfail_503(self):
        r = requests.post(
            f"{BASE}/api/webhook/payment/razorpay",
            data=b"{}",
            headers={"Content-Type": "application/json",
                      "X-Razorpay-Signature": "anything"},
            timeout=20,
        )
        # RAZORPAY_WEBHOOK_SECRET not configured → 503 (server misconfig),
        # never 500 or 2xx.
        assert r.status_code == 503, r.text
        assert "webhook_secret_not_configured" in json.dumps(r.json()), r.json()

    def test_unknown_payment_provider_404(self):
        r = requests.post(
            f"{BASE}/api/webhook/payment/monopoly",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        assert r.status_code == 404, r.text
        assert "unknown_payment_provider" in json.dumps(r.json()), r.json()


# ===========================================================================
# MILESTONE G — AI gateway
# ===========================================================================
class TestMilestoneG_AIGateway:
    def test_openai_admin_detail_test_mode(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/openai",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "TEST_MODE", r.json()

    def test_anthropic_admin_detail_test_mode(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/anthropic",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "TEST_MODE", r.json()

    def test_gemini_admin_detail_test_mode(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/gemini",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "TEST_MODE", r.json()


# ===========================================================================
# MILESTONE H — ElevenLabs + webhook_url surface polish
# ===========================================================================
class TestMilestoneH_ElevenLabs:
    def test_elevenlabs_admin_detail(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations/elevenlabs",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "CONFIGURATION_REQUIRED"
        assert "ELEVENLABS_API_KEY" in body.get("missing_env", []), body

    def test_elevenlabs_test_connection_reports_configuration_required(self, admin_token):
        r = requests.post(
            f"{BASE}/api/v1/admin/integrations/elevenlabs/test",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is False, body
        detail = str(body.get("detail") or body.get("message") or "")
        assert "CONFIGURATION_REQUIRED" in detail, body
        assert "ELEVENLABS_API_KEY" in detail, body


# ===========================================================================
# REGRESSION — existing v0.1 / Phase 1-6 behavior
# ===========================================================================
class TestRegression:
    def test_fixture_login_and_me(self, fixture_token):
        r = requests.get(f"{BASE}/api/v1/auth/me", headers=_auth(fixture_token), timeout=20)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["email"] == FIXTURE_EMAIL

    def test_billing_checkout_returns_stripe_url(self, fixture_token):
        r = requests.post(
            f"{BASE}/api/v1/billing/checkout",
            json={"lookup_key": "pro_monthly",
                   "origin_url": "https://lynk-preview-2.preview.emergentagent.com"},
            headers=_auth(fixture_token), timeout=30,
        )
        # Either 200 with a checkout_url, or 402/409 if already-pro — MUST not 500.
        assert r.status_code in (200, 201, 400, 402, 409), r.text
        if r.status_code in (200, 201):
            body = r.json()
            url = body.get("checkout_url") or body.get("url") or ""
            assert "stripe" in url.lower() or "checkout" in url.lower(), body

    def test_privacy_export_no_password_hash_leak(self, fixture_token):
        # /privacy/export is POST — spawns a job, then GET /{job_id}.
        r = requests.post(
            f"{BASE}/api/v1/privacy/export",
            json={}, headers=_auth(fixture_token), timeout=30,
        )
        assert r.status_code in (200, 201, 202), r.text
        job_id = (r.json().get("job_id") or r.json().get("id")
                    or r.json().get("export_id"))
        assert job_id, r.text
        # Poll a couple of times for completion.
        text = ""
        for _ in range(5):
            r2 = requests.get(
                f"{BASE}/api/v1/privacy/export/{job_id}",
                headers=_auth(fixture_token), timeout=30,
            )
            assert r2.status_code == 200, r2.text
            text = r2.text
            j = r2.json()
            if j.get("status") in ("ready", "complete", "completed", "done"):
                break
            time.sleep(1)
        # NEVER leak password_hash or bcrypt markers.
        assert "password_hash" not in text, "password_hash leaked in export"
        assert "$2b$" not in text, "bcrypt marker leaked in export"
        assert "$2a$" not in text, "bcrypt marker leaked in export"

    def test_admin_user_detail_masks_sealed(self, admin_token):
        # /admin/users?q=... returns light rows (no sealed fields exposed).
        # Sealed-mask literal lives on /admin/users/{id}.
        r0 = requests.get(
            f"{BASE}/api/v1/admin/users?q=fixture-ead",
            headers=_auth(admin_token), timeout=20,
        )
        assert r0.status_code == 200, r0.text
        rows = r0.json().get("users", [])
        assert rows, r0.text
        uid = rows[0]["id"]
        r = requests.get(
            f"{BASE}/api/v1/admin/users/{uid}",
            headers=_auth(admin_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        text = r.text
        # Sealed sensitive fields must render the literal mask.
        assert "•••• (sealed)" in text, \
            "expected sealed-mask literal '•••• (sealed)' in admin user detail"
        # Never leaks credentials either.
        assert "password_hash" not in text
        assert "$2b$" not in text and "$2a$" not in text

    def test_support_cannot_write_integrations(self, support_token):
        # Milestone A already-observed: support must not be able to test/disable.
        r = requests.post(
            f"{BASE}/api/v1/admin/integrations/resend/disable",
            headers=_auth(support_token), timeout=20,
        )
        assert r.status_code in (401, 403), r.text
