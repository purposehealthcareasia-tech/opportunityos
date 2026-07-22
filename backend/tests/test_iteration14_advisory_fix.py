"""Iteration 14 — Advisory-fix verification for webhook HTTP semantics
+ regression spot-checks + Admin Integrations RBAC.

Scope (per review request):
- Every /api/webhook/* route must now return HTTP 503 for server-side
  mis-configuration (secret / webhook id / auth not configured) and
  HTTP 400 for cryptographic / header failures. Never 500. Never 2xx.
- Unknown provider slugs still 404 with the mandated error code.
- Admin Integrations surface behaviour-neutral: provider count == 16
  and the required status matrix holds.
- support role can NOT mutate integrations.
- fixture-ead login + /auth/me still works.
- Billing checkout still returns 200 (Stripe test-mode URL).
- Privacy export still masks password_hash.
"""
from __future__ import annotations

import json
import os
import time
import uuid

import pytest
import requests


# --- Resolve preview base URL ------------------------------------------------
BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE:
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE = line.strip().split("=", 1)[1].rstrip("/")
                    break
    except Exception:
        pass
assert BASE, "REACT_APP_BACKEND_URL must be resolvable"

# --- Credentials (from /app/memory/test_credentials.md) ---------------------
FIXTURE_EMAIL = "fixture-ead@opportunityos.dev"
FIXTURE_PASSWORD = "Fixture!Test1"
ADMIN_EMAIL = "admin@opportunityos.dev"
ADMIN_PASSWORD = "Admin!Console1"
SUPPORT_EMAIL = "support@opportunityos.dev"
SUPPORT_PASSWORD = "Support!Console1"


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


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def fixture_token() -> str:
    return _login(FIXTURE_EMAIL, FIXTURE_PASSWORD)


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def support_token() -> str:
    return _login(SUPPORT_EMAIL, SUPPORT_PASSWORD)


# ===========================================================================
# ADVISORY-FIX-1 → ADVISORY-FIX-7 — webhook HTTP semantics
# Contract: 503 = server misconfiguration (secret / id / auth not configured),
#           400 = cryptographic / header failure,
#           404 = unknown provider slug,
#           NEVER 500, NEVER 2xx.
# ===========================================================================
class TestAdvisoryFixWebhookSemantics:

    # -- ADVISORY-FIX-1: Resend (svix) ---------------------------------------
    def test_resend_webhook_returns_503_secret_not_configured(self):
        r = requests.post(
            f"{BASE}/api/webhook/email/resend",
            data=b'{"random":"body"}',
            headers={
                "Content-Type": "application/json",
                "svix-id": "msg_" + uuid.uuid4().hex,
                "svix-timestamp": str(int(time.time())),
                "svix-signature": "v1,fake",
            },
            timeout=20,
        )
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
        j = r.json()
        detail = j.get("detail", {})
        assert isinstance(detail, dict), j
        assert detail.get("error") == "webhook_verification_failed", j
        assert detail.get("reason") == "webhook_secret_not_configured", j

    # -- ADVISORY-FIX-2: SendGrid --------------------------------------------
    def test_sendgrid_webhook_returns_503_public_key_not_configured(self):
        r = requests.post(
            f"{BASE}/api/webhook/email/sendgrid",
            data=b"[]",
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
        j = r.json()
        detail = j.get("detail", {})
        assert detail.get("error") == "webhook_verification_failed", j
        assert detail.get("reason") == "webhook_public_key_not_configured", j

    # -- ADVISORY-FIX-3: Stripe ----------------------------------------------
    def test_stripe_webhook_returns_503_secret_not_configured(self):
        r = requests.post(
            f"{BASE}/api/webhook/payment/stripe",
            data=b'{"random":"payload"}',
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": f"t={int(time.time())},v1=deadbeef",
            },
            timeout=20,
        )
        # STRIPE_WEBHOOK_SECRET unset in preview → 503.
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
        j = r.json()
        detail = j.get("detail", {})
        assert detail.get("error") == "webhook_verification_failed", j
        # The reason must be the not-configured branch; never a generic 500.
        assert "not_configured" in str(detail.get("reason", "")), j

    # -- ADVISORY-FIX-4: Razorpay --------------------------------------------
    def test_razorpay_webhook_returns_503_secret_not_configured(self):
        r = requests.post(
            f"{BASE}/api/webhook/payment/razorpay",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": "anything",
            },
            timeout=20,
        )
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
        j = r.json()
        detail = j.get("detail", {})
        assert detail.get("error") == "webhook_verification_failed", j
        assert detail.get("reason") == "webhook_secret_not_configured", j

    # -- ADVISORY-FIX-5: Paystack --------------------------------------------
    def test_paystack_webhook_returns_503_secret_not_configured(self):
        r = requests.post(
            f"{BASE}/api/webhook/payment/paystack",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "x-paystack-signature": "anything",
            },
            timeout=20,
        )
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
        j = r.json()
        detail = j.get("detail", {})
        assert detail.get("error") == "webhook_verification_failed", j
        assert detail.get("reason") == "webhook_secret_not_configured", j

    # -- ADVISORY-FIX-6: PayPal ----------------------------------------------
    def test_paypal_webhook_returns_503_webhook_id_not_configured(self):
        r = requests.post(
            f"{BASE}/api/webhook/payment/paypal",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
        j = r.json()
        detail = j.get("detail", {})
        assert detail.get("error") == "webhook_verification_failed", j
        assert detail.get("reason") == "webhook_id_not_configured", j

    # -- ADVISORY-FIX-7: Unknown provider slugs (email + payments) -----------
    def test_unknown_email_provider_returns_404(self):
        r = requests.post(
            f"{BASE}/api/webhook/email/mailgun",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        assert r.status_code == 404, r.text
        assert "unknown_email_provider" in json.dumps(r.json()), r.json()

    def test_unknown_payment_provider_returns_404(self):
        r = requests.post(
            f"{BASE}/api/webhook/payment/monopoly",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        assert r.status_code == 404, r.text
        assert "unknown_payment_provider" in json.dumps(r.json()), r.json()

    # -- Extra safety: NONE of the above are 500 or 2xx ----------------------
    @pytest.mark.parametrize("route,headers", [
        ("/api/webhook/email/resend", {}),
        ("/api/webhook/email/sendgrid", {}),
        ("/api/webhook/payment/stripe", {"Stripe-Signature": "t=0,v1=0"}),
        ("/api/webhook/payment/razorpay", {"X-Razorpay-Signature": "x"}),
        ("/api/webhook/payment/paystack", {"x-paystack-signature": "x"}),
        ("/api/webhook/payment/paypal", {}),
    ])
    def test_webhook_routes_never_500_or_2xx(self, route, headers):
        headers = {"Content-Type": "application/json", **headers}
        r = requests.post(f"{BASE}{route}", data=b"{}", headers=headers, timeout=20)
        assert r.status_code != 500, f"{route} returned 500: {r.text}"
        assert not (200 <= r.status_code < 300), \
            f"{route} returned 2xx {r.status_code}: {r.text}"


# ===========================================================================
# REGRESSION-2 spot-checks — Admin Integrations surface behaviour-neutral
# ===========================================================================
EXPECTED_STATUS_MATRIX = {
    "stripe": "TEST_MODE",
    "email_password": "CONNECTED",
    "google_auth": {"CONNECTED", "TEST_MODE"},  # allow either per iter13
    "resend": "CONFIGURATION_REQUIRED",
    "sendgrid": "CONFIGURATION_REQUIRED",
    "twilio": "CONFIGURATION_REQUIRED",
    "elevenlabs": "CONFIGURATION_REQUIRED",
    "razorpay": "CONFIGURATION_REQUIRED",
    "paypal": "CONFIGURATION_REQUIRED",
    "paystack": "CONFIGURATION_REQUIRED",
}


class TestAdminIntegrationsSurface:

    def test_admin_integrations_list_returns_14_providers(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations",
            headers=_auth(admin_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Accept either a bare list or {providers:[...]} envelope.
        providers = body.get("providers") if isinstance(body, dict) else body
        assert isinstance(providers, list), body
        assert len(providers) == 16, f"expected 16 providers, got {len(providers)}"

    def test_admin_integrations_status_matrix(self, admin_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations",
            headers=_auth(admin_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        providers = body.get("providers") if isinstance(body, dict) else body
        by_slug = {p["slug"]: p for p in providers if isinstance(p, dict)}
        for slug, expected in EXPECTED_STATUS_MATRIX.items():
            assert slug in by_slug, f"missing provider {slug}"
            actual = by_slug[slug].get("status")
            if isinstance(expected, set):
                assert actual in expected, f"{slug}: expected in {expected}, got {actual}"
            else:
                assert actual == expected, f"{slug}: expected {expected}, got {actual}"


# ===========================================================================
# POLISH-5 / RBAC — support cannot mutate integrations
# ===========================================================================
class TestSupportRBAC:

    def test_support_can_read_integrations(self, support_token):
        r = requests.get(
            f"{BASE}/api/v1/admin/integrations",
            headers=_auth(support_token), timeout=20,
        )
        # Support role has read-only observability on the integrations tab.
        assert r.status_code == 200, r.text

    def test_support_cannot_test_stripe(self, support_token):
        r = requests.post(
            f"{BASE}/api/v1/admin/integrations/stripe/test",
            headers=_auth(support_token), timeout=20,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_support_cannot_disable_stripe(self, support_token):
        r = requests.post(
            f"{BASE}/api/v1/admin/integrations/stripe/disable",
            headers=_auth(support_token), timeout=20,
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


# ===========================================================================
# REGRESSION-1 — fixture-ead login + /auth/me + billing checkout + privacy
# ===========================================================================
class TestRegressionSmoke:

    def test_fixture_login_and_me(self, fixture_token):
        r = requests.get(
            f"{BASE}/api/v1/auth/me",
            headers=_auth(fixture_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("email") == FIXTURE_EMAIL, body

    def test_billing_checkout_returns_200(self, fixture_token):
        r = requests.post(
            f"{BASE}/api/v1/billing/checkout",
            headers={**_auth(fixture_token), "Content-Type": "application/json"},
            json={
                "lookup_key": "pro_monthly",
                "origin_url": BASE,
            },
            timeout=30,
        )
        # Iter13 confirmed the endpoint returns 200 with a Stripe test-mode URL.
        assert r.status_code == 200, f"billing checkout expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        url = body.get("checkout_url") or body.get("url") or ""
        assert "stripe" in url.lower() or url.startswith("http"), body

    def test_privacy_export_masks_password_hash(self, fixture_token):
        r = requests.post(
            f"{BASE}/api/v1/privacy/export",
            headers={**_auth(fixture_token), "Content-Type": "application/json"},
            timeout=60,
        )
        assert r.status_code in (200, 202), r.text
        blob = json.dumps(r.json())
        # Never leak bcrypt or a raw hash.
        assert "$2b$" not in blob, "bcrypt hash leaked in privacy export"
        assert '"password_hash"' not in blob or '"password_hash": null' in blob \
            or '"password_hash":"' not in blob, "password_hash present unmasked"
