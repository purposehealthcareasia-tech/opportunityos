"""Iter18 live preview smoke tests — covers the P1 items in the review request
against https://lynk-preview-2.preview.emergentagent.com.

- /api/health public
- /api/v1/admin/health (401 without cookie, then with admin cookie)
- /api/v1/admin/integrations 16-provider audit
- /api/internal/fixture/rebase 401 / 403 / 200 semantics
- Fixture user critical journeys (GET-only)
- Privacy export sensitive-scrub
- VAPID public key (no private leak)
- Google OAuth session (4xx, not 500)
- Apple status configured=false

Env values are NEVER printed. Only presence/shape assertions.
"""
import os
import json
import re
import time
import requests

BASE = "https://lynk-preview-2.preview.emergentagent.com"

# Load INTERNAL_SERVICE_TOKEN and VAPID_PRIVATE_KEY safely without echoing them
def _read_env(key):
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return None

INTERNAL_TOKEN = _read_env("INTERNAL_SERVICE_TOKEN")
VAPID_PRIVATE = _read_env("VAPID_PRIVATE_KEY")

results = []

def rec(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append((name, ok, detail))
    print(f"[{status}] {name} :: {detail}")


# ---------- /api/health public ----------
r = requests.get(f"{BASE}/api/health", timeout=15)
data = r.json() if r.status_code == 200 else {}
required = {"ok", "mongo", "phase", "policy_text_version"}
leaked = {"prod_mode", "ci_test_issuer_enabled"} & set(data.keys())
rec("api_health_public",
    r.status_code == 200 and required.issubset(data.keys()) and not leaked,
    f"status={r.status_code} keys={sorted(data.keys())} leaked={leaked}")

# no VAPID private leak in /api/health body
if VAPID_PRIVATE:
    assert VAPID_PRIVATE not in r.text, "VAPID private key leaked in /api/health!"


# ---------- /api/v1/admin/health (no cookie => 401) ----------
r = requests.get(f"{BASE}/api/v1/admin/health", timeout=15)
rec("admin_health_no_cookie_401", r.status_code == 401, f"status={r.status_code}")


# ---------- Admin login ----------
admin_sess = requests.Session()
lr = admin_sess.post(f"{BASE}/api/v1/auth/login",
                      json={"email": "admin@opportunityos.dev",
                            "password": "Admin!Console1"}, timeout=15)
admin_token = None
if lr.status_code == 200:
    body = lr.json()
    admin_token = body.get("access_token")
    rec("admin_login", True, f"status=200 has_access_token={bool(admin_token)} cookies={list(admin_sess.cookies.keys())}")
else:
    rec("admin_login", False, f"status={lr.status_code} body_snip={lr.text[:150]}")


def _auth_headers(token, sess):
    h = {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    # CSRF cookie -> header for POSTs
    csrf = sess.cookies.get("oppos_csrf")
    if csrf:
        h["X-CSRF-Token"] = csrf
    return h


# ---------- /api/v1/admin/health with admin cookie ----------
r = admin_sess.get(f"{BASE}/api/v1/admin/health",
                   headers=_auth_headers(admin_token, admin_sess), timeout=15)
if r.status_code == 200:
    ah = r.json()
    has_prod = "prod_mode" in ah
    has_ci = "ci_test_issuer_enabled" in ah
    has_sha = isinstance(ah.get("build_sha"), str) and len(ah.get("build_sha", "")) > 0
    rec("admin_health_authed",
        has_prod and has_ci and has_sha,
        f"prod_mode={has_prod} ci_test_issuer_enabled={has_ci} build_sha_present={has_sha}")
    if VAPID_PRIVATE:
        assert VAPID_PRIVATE not in r.text, "VAPID private key leaked in admin/health!"
else:
    rec("admin_health_authed", False, f"status={r.status_code}")


# ---------- /api/v1/admin/integrations 16 rows ----------
r = admin_sess.get(f"{BASE}/api/v1/admin/integrations",
                   headers=_auth_headers(admin_token, admin_sess), timeout=20)
if r.status_code == 200:
    ai = r.json()
    # Response might be a dict with 'providers' key or a list — normalize
    providers = ai.get("providers") if isinstance(ai, dict) else ai
    canonical = {"stripe", "razorpay", "paypal", "paystack",
                 "google_auth", "apple_auth", "email_password",
                 "resend", "sendgrid", "twilio", "push_notifications",
                 "openai", "anthropic", "gemini", "elevenlabs", "media_storage"}
    found = {p.get("provider") or p.get("id") or p.get("key") or p.get("name") for p in providers}
    valid_statuses = {"CONNECTED", "TEST_MODE", "CONFIGURATION_REQUIRED", "DEGRADED", "DISABLED"}
    status_ok = all((p.get("status") in valid_statuses) for p in providers)
    rec("admin_integrations_16",
        len(providers) == 16 and canonical == found and status_ok,
        f"count={len(providers)} missing={canonical - found} extra={found - canonical} status_ok={status_ok}")
    if VAPID_PRIVATE:
        assert VAPID_PRIVATE not in r.text, "VAPID private key leaked in admin/integrations!"
else:
    rec("admin_integrations_16", False, f"status={r.status_code} snip={r.text[:150]}")


# ---------- /api/internal/fixture/rebase ----------
# (a) no token -> 401
r = requests.post(f"{BASE}/api/internal/fixture/rebase", timeout=15)
try:
    err_a = r.json().get("detail", {}).get("error") if r.status_code == 401 else None
except Exception:
    err_a = None
rec("fixture_rebase_no_token_401",
    r.status_code == 401 and err_a == "service_token_missing",
    f"status={r.status_code} err={err_a}")

# (b) wrong token -> 403
r = requests.post(f"{BASE}/api/internal/fixture/rebase",
                  headers={"X-Service-Token": "totally-wrong"}, timeout=15)
try:
    err_b = r.json().get("detail", {}).get("error") if r.status_code == 403 else None
except Exception:
    err_b = None
rec("fixture_rebase_wrong_token_403",
    r.status_code == 403 and err_b == "service_token_invalid",
    f"status={r.status_code} err={err_b}")

# (c) correct token -> 200
r = requests.post(f"{BASE}/api/internal/fixture/rebase",
                  headers={"X-Service-Token": INTERNAL_TOKEN or ""}, timeout=30)
body_c = r.json() if r.status_code == 200 else {}
token_leaked = INTERNAL_TOKEN and INTERNAL_TOKEN in r.text
rec("fixture_rebase_correct_token_200",
    r.status_code == 200 and body_c.get("ok") is True
    and isinstance(body_c.get("fixture_user_id"), str)
    and not token_leaked,
    f"status={r.status_code} ok={body_c.get('ok')} has_user_id={'fixture_user_id' in body_c} token_leaked={bool(token_leaked)}")


# ---------- Fixture user login ----------
fx = requests.Session()
lr = fx.post(f"{BASE}/api/v1/auth/login",
             json={"email": "fixture-ead@opportunityos.dev",
                   "password": "Fixture!Test1"}, timeout=15)
fx_token = None
if lr.status_code == 200:
    fx_token = lr.json().get("access_token")
    rec("fixture_login", True, f"status=200 has_token={bool(fx_token)}")
else:
    rec("fixture_login", False, f"status={lr.status_code}")


# ---------- Fixture GET journeys ----------
FX_ENDPOINTS = [
    "/api/v1/auth/me",
    "/api/v1/consents",
    "/api/v1/passport/state",
    "/api/v1/preferences/me",
    "/api/v1/eligibility/coverage-preview",
    "/api/v1/jobs/feed",
    "/api/v1/applications",
    "/api/v1/subscriptions/me",
    "/api/v1/tracker",
    "/api/v1/notifications/preferences",
    "/api/v1/notifications/vapid-public-key",
]
for ep in FX_ENDPOINTS:
    r = fx.get(f"{BASE}{ep}", headers=_auth_headers(fx_token, fx), timeout=15)
    detail = f"status={r.status_code}"
    ok = r.status_code == 200
    if ep == "/api/v1/jobs/feed" and ok:
        try:
            totals = r.json().get("totals", {})
            passing = totals.get("passing")
            excluded = totals.get("excluded")
            ok = passing == 9 and excluded == 6
            detail += f" passing={passing} excluded={excluded}"
        except Exception as e:
            ok = False
            detail += f" parse_err={e}"
    if ep == "/api/v1/notifications/vapid-public-key" and ok:
        try:
            body = r.json()
            pk = body.get("public_key")
            cats = body.get("supported_categories", [])
            ok = body.get("ok") is True and isinstance(pk, str) and len(pk) > 10 and len(cats) == 5
            detail += f" ok={body.get('ok')} pk_len={len(pk) if isinstance(pk,str) else 0} cats={len(cats)}"
            if VAPID_PRIVATE:
                assert VAPID_PRIVATE not in r.text, "VAPID private key leaked in vapid-public-key!"
        except Exception as e:
            ok = False
            detail += f" parse_err={e}"
    rec(f"fx_get:{ep}", ok, detail)


# ---------- Privacy export sensitive-scrub ----------
r = fx.post(f"{BASE}/api/v1/privacy/export",
            headers=_auth_headers(fx_token, fx), timeout=15)
if r.status_code in (200, 202):
    job = r.json()
    job_id = job.get("job_id") or job.get("id")
    # poll for readiness
    dl = None
    for _ in range(15):
        pr = fx.get(f"{BASE}/api/v1/privacy/export/{job_id}",
                    headers=_auth_headers(fx_token, fx), timeout=15)
        if pr.status_code == 200:
            pb = pr.json()
            if pb.get("status") in ("ready", "complete", "done") or pb.get("download"):
                dl = pb
                break
        time.sleep(1)
    if dl:
        serialized = json.dumps(dl.get("download", dl))
        forbidden = ["password", "password_hash", "csrf_token", "session_id",
                     "totp_secret", "recovery_codes", "bcrypt_hash", "$2b$"]
        # some fields like "password" as key might legitimately not appear at all;
        # tolerance: none of them should appear in serialization anywhere.
        hits = [t for t in forbidden if t in serialized]
        rec("privacy_export_no_sensitive_leak",
            len(hits) == 0,
            f"forbidden_hits={hits} serialized_len={len(serialized)}")
    else:
        rec("privacy_export_no_sensitive_leak", False, "export never ready after 15s")
else:
    rec("privacy_export_no_sensitive_leak", False, f"submit_status={r.status_code}")


# ---------- VAPID public key public (no auth) ----------
r = requests.get(f"{BASE}/api/v1/notifications/vapid-public-key", timeout=15)
body = r.json() if r.status_code == 200 else {}
pk = body.get("public_key", "")
cats = body.get("supported_categories", [])
private_leak = bool(VAPID_PRIVATE and VAPID_PRIVATE in r.text)
rec("vapid_public_key_public",
    r.status_code == 200 and body.get("ok") is True
    and isinstance(pk, str) and len(pk) > 10 and len(cats) == 5
    and not private_leak,
    f"status={r.status_code} ok={body.get('ok')} cats={len(cats)} private_leak={private_leak}")


# ---------- Google OAuth session ----------
r = requests.get(f"{BASE}/api/v1/auth/google/session?session_id=fake", timeout=15)
rec("google_session_no_500",
    400 <= r.status_code < 500,
    f"status={r.status_code}")


# ---------- Apple status ----------
r = requests.get(f"{BASE}/api/v1/auth/apple/status", timeout=15)
body = r.json() if r.status_code == 200 else {}
rec("apple_status_configured_false",
    r.status_code == 200 and body.get("configured") is False,
    f"status={r.status_code} configured={body.get('configured')}")


# ---------- Malformed webpush subscription live probe (P0 KEY VERIFICATION) ----------
csrf = fx.cookies.get("oppos_csrf")
sub_hdr = _auth_headers(fx_token, fx)
sub_hdr["Content-Type"] = "application/json"

# (a) malformed base64 keys
r = fx.post(f"{BASE}/api/v1/notifications/subscribe",
            headers=sub_hdr,
            json={"endpoint": "https://fcm.googleapis.com/fcm/send/abc",
                  "keys": {"p256dh": "not-base-64-!!!!!", "auth": "not-base-64-!!!"},
                  "category": "application"}, timeout=15)
err = None
try:
    err = r.json().get("detail", {}).get("error") if r.status_code == 400 else None
except Exception:
    pass
rec("webpush_subscribe_malformed_base64",
    r.status_code == 400 and err == "subscription_malformed_keys",
    f"status={r.status_code} err={err}")

# (b) non-https endpoint
r = fx.post(f"{BASE}/api/v1/notifications/subscribe",
            headers=sub_hdr,
            json={"endpoint": "ftp://x.example/y",
                  "keys": {"p256dh": "BOm3sB0" + "a" * 80, "auth": "abcd" * 5},
                  "category": "application"}, timeout=15)
err = None
try:
    err = r.json().get("detail", {}).get("error") if r.status_code == 400 else None
except Exception:
    pass
rec("webpush_subscribe_non_https",
    r.status_code == 400 and err == "subscription_invalid_endpoint",
    f"status={r.status_code} err={err}")


# ---------- SUMMARY ----------
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
print(f"\n=== iter18 live smoke: {passed}/{total} PASS ===")
for name, ok, detail in results:
    print(("PASS" if ok else "FAIL") + " " + name + " -- " + detail)
