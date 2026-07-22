"""Iteration 15 — advisory-fix HARDENED re-verification.

Contract (re-verified after the three polish tweaks in iter14):
  - webhooks_email.py uses an explicit allow-set
    {webhook_secret_not_configured, webhook_public_key_not_configured}
    for server-misconfig → HTTP 503; anything else → 400.
  - webhooks_payment.py uses an explicit allow-set
    (_SERVER_MISCONFIG_EXACT + _SERVER_MISCONFIG_PREFIX) for server-misconfig
    → HTTP 503; anything else → 400.
  - Unknown provider slug → 404 (unknown_email_provider / unknown_payment_provider).
  - Support role RBAC: POST /api/v1/admin/integrations/stripe/test → 403.
  - Regression: fixture-ead /auth/me 200; billing checkout 200; providers==14
    with the same status matrix.
"""
from __future__ import annotations

import json
import os
import time

import pytest
import requests


def _resolve_base_url() -> str:
    v = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
    if v:
        return v
    # Fallback: read from the frontend .env so the same suite works whether
    # or not the shell exported REACT_APP_BACKEND_URL.
    try:
        with open("/app/frontend/.env") as fh:
            for line in fh:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.strip().split("=", 1)[1].rstrip("/")
    except Exception:
        pass
    return ""


BASE_URL = _resolve_base_url()
assert BASE_URL, "REACT_APP_BACKEND_URL must be set (or /app/frontend/.env readable)"

ADMIN_EMAIL = "admin@opportunityos.dev"
ADMIN_PASSWORD = "Admin!Console1"
SUPPORT_EMAIL = "support@opportunityos.dev"
SUPPORT_PASSWORD = "Support!Console1"
FIXTURE_EMAIL = "fixture-ead@opportunityos.dev"
FIXTURE_PASSWORD = "Fixture!Test1"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _login(email: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in login body for {email}: {r.text[:200]}"
    return tok


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def support_token() -> str:
    return _login(SUPPORT_EMAIL, SUPPORT_PASSWORD)


@pytest.fixture(scope="module")
def fixture_token() -> str:
    return _login(FIXTURE_EMAIL, FIXTURE_PASSWORD)


# ---------------------------------------------------------------------------
# ADVISORY-FIX-HARDENED — webhook HTTP-semantics
# ---------------------------------------------------------------------------


def _post_webhook(path: str, body: bytes | dict, headers: dict | None = None):
    if isinstance(body, dict):
        body = json.dumps(body).encode("utf-8")
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    return requests.post(f"{BASE_URL}{path}", data=body, headers=hdrs, timeout=30)


class TestAdvisoryFixHardened:
    """Webhook routes must return 503 for server-misconfig, never 500/2xx."""

    def test_1_email_resend_no_secret_returns_503(self):
        r = _post_webhook("/api/webhook/email/resend", {"random": "body"})
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text[:200]}"
        body = r.json()
        detail = body.get("detail", body)
        assert detail.get("error") == "webhook_verification_failed", detail
        assert detail.get("reason") == "webhook_secret_not_configured", detail

    def test_2_email_sendgrid_no_key_returns_503(self):
        r = _post_webhook("/api/webhook/email/sendgrid", {"random": "body"})
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text[:200]}"
        detail = r.json().get("detail", r.json())
        assert detail.get("error") == "webhook_verification_failed"
        assert detail.get("reason") == "webhook_public_key_not_configured", detail

    def test_3_payment_stripe_no_secret_returns_503(self):
        r = _post_webhook(
            "/api/webhook/payment/stripe",
            {"id": "evt_fake_1", "type": "payment_intent.succeeded"},
            headers={"Stripe-Signature": "t=123,v1=deadbeef"},
        )
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text[:200]}"
        detail = r.json().get("detail", r.json())
        assert detail.get("error") == "webhook_verification_failed"
        # stripe reason is webhook_secret_not_configured when unset
        assert "not_configured" in (detail.get("reason") or ""), detail

    def test_4_payment_razorpay_no_secret_returns_503(self):
        r = _post_webhook(
            "/api/webhook/payment/razorpay",
            {"id": "evt_fake"},
            headers={"X-Razorpay-Signature": "beefdead"},
        )
        assert r.status_code == 503
        detail = r.json().get("detail", r.json())
        assert detail.get("reason") == "webhook_secret_not_configured", detail

    def test_5_payment_paystack_no_secret_returns_503(self):
        r = _post_webhook(
            "/api/webhook/payment/paystack",
            {"data": {"id": 42}},
            headers={"x-paystack-signature": "deadbeef"},
        )
        assert r.status_code == 503
        detail = r.json().get("detail", r.json())
        assert detail.get("reason") == "webhook_secret_not_configured", detail

    def test_6_payment_paypal_no_id_returns_503(self):
        r = _post_webhook("/api/webhook/payment/paypal", {"id": "WH-XYZ"})
        assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text[:200]}"
        detail = r.json().get("detail", r.json())
        # PayPal signals server-misconfig with webhook_id_not_configured OR
        # auth_failed / upstream_error prefix (both under _SERVER_MISCONFIG_PREFIX).
        reason = detail.get("reason") or ""
        assert (
            reason == "webhook_id_not_configured"
            or reason.startswith(("auth_failed", "upstream_error"))
        ), detail

    def test_7_unknown_email_provider_returns_404(self):
        r = _post_webhook("/api/webhook/email/does_not_exist", {})
        assert r.status_code == 404
        detail = r.json().get("detail", r.json())
        assert detail.get("error") == "unknown_email_provider", detail

    def test_8_unknown_payment_provider_returns_404(self):
        r = _post_webhook("/api/webhook/payment/does_not_exist", {})
        assert r.status_code == 404
        detail = r.json().get("detail", r.json())
        assert detail.get("error") == "unknown_payment_provider", detail

    @pytest.mark.parametrize(
        "path,extra_headers",
        [
            ("/api/webhook/email/resend", None),
            ("/api/webhook/email/sendgrid", None),
            ("/api/webhook/payment/stripe", {"Stripe-Signature": "t=1,v1=aa"}),
            ("/api/webhook/payment/razorpay", {"X-Razorpay-Signature": "aa"}),
            ("/api/webhook/payment/paystack", {"x-paystack-signature": "aa"}),
            ("/api/webhook/payment/paypal", None),
        ],
    )
    def test_9_never_returns_500_or_2xx(self, path, extra_headers):
        """Parametric guardrail — must NEVER be 500 nor 2xx for random body."""
        r = _post_webhook(path, {"random": "gibberish", "n": time.time()},
                          headers=extra_headers)
        assert r.status_code not in range(200, 300), \
            f"{path} returned 2xx {r.status_code} on unverified body: {r.text[:200]}"
        assert r.status_code != 500, \
            f"{path} returned 500 on unverified body: {r.text[:200]}"
        assert r.status_code in (400, 503), \
            f"{path} unexpected status {r.status_code}: {r.text[:200]}"


# ---------------------------------------------------------------------------
# RBAC — support role can NOT invoke integration test/disable
# ---------------------------------------------------------------------------


class TestSupportRBAC:
    def test_support_cannot_test_stripe(self, support_token: str):
        r = requests.post(
            f"{BASE_URL}/api/v1/admin/integrations/stripe/test",
            headers={"Authorization": f"Bearer {support_token}"},
            timeout=30,
        )
        assert r.status_code == 403, \
            f"expected 403 for support role, got {r.status_code}: {r.text[:200]}"

    def test_support_cannot_disable_stripe(self, support_token: str):
        r = requests.post(
            f"{BASE_URL}/api/v1/admin/integrations/stripe/disable",
            headers={"Authorization": f"Bearer {support_token}"},
            timeout=30,
        )
        assert r.status_code == 403, \
            f"expected 403 for support role, got {r.status_code}: {r.text[:200]}"


# ---------------------------------------------------------------------------
# REGRESSION — /auth/me + billing checkout + providers list unchanged
# ---------------------------------------------------------------------------


class TestRegression:
    def test_fixture_auth_me_200(self, fixture_token: str):
        r = requests.get(
            f"{BASE_URL}/api/v1/auth/me",
            headers={"Authorization": f"Bearer {fixture_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        assert r.json().get("email") == FIXTURE_EMAIL

    def test_billing_checkout_200(self, fixture_token: str):
        r = requests.post(
            f"{BASE_URL}/api/v1/billing/checkout",
            headers={"Authorization": f"Bearer {fixture_token}",
                     "Content-Type": "application/json"},
            json={"lookup_key": "pro_monthly", "origin_url": BASE_URL},
            timeout=30,
        )
        assert r.status_code in (200, 201), \
            f"unexpected status: {r.status_code} {r.text[:200]}"
        body = r.json()
        url = body.get("checkout_url") or body.get("url") or ""
        assert "stripe" in url.lower() or url.startswith("http"), body

    def test_providers_count_and_status_matrix(self, admin_token: str):
        r = requests.get(
            f"{BASE_URL}/api/v1/admin/integrations",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        providers = body.get("providers") or body.get("items") or body
        # Support both {providers: [...]} and bare list forms
        if isinstance(providers, dict) and "items" in providers:
            providers = providers["items"]
        assert isinstance(providers, list), f"unexpected shape: {type(providers)}"
        assert len(providers) == 14, f"expected 14 providers, got {len(providers)}"
        status_by_slug = {p["slug"]: p.get("status") for p in providers}
        # Expected matrix (from review request)
        assert status_by_slug.get("stripe") == "TEST_MODE", status_by_slug
        assert status_by_slug.get("email_password") == "CONNECTED", status_by_slug
        assert status_by_slug.get("google_auth") == "CONNECTED", status_by_slug
        for slug in (
            "resend", "sendgrid", "twilio", "elevenlabs",
            "razorpay", "paypal", "paystack",
        ):
            assert status_by_slug.get(slug) == "CONFIGURATION_REQUIRED", \
                f"{slug} unexpected: {status_by_slug.get(slug)}"
