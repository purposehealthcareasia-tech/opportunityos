"""Retry failed items with corrected paths / payloads."""
import json, requests

BASE = "https://lynk-preview-2.preview.emergentagent.com"

def _read_env(key):
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()

# fixture login
fx = requests.Session()
lr = fx.post(f"{BASE}/api/v1/auth/login",
             json={"email": "fixture-ead@opportunityos.dev",
                   "password": "Fixture!Test1"}, timeout=15)
fx_token = lr.json().get("access_token")
fx_hdr = {"Authorization": f"Bearer {fx_token}",
          "X-CSRF-Token": fx.cookies.get("oppos_csrf") or "",
          "Content-Type": "application/json"}

# admin login
adm = requests.Session()
lr = adm.post(f"{BASE}/api/v1/auth/login",
              json={"email": "admin@opportunityos.dev",
                    "password": "Admin!Console1"}, timeout=15)
adm_token = lr.json().get("access_token")
adm_hdr = {"Authorization": f"Bearer {adm_token}",
           "X-CSRF-Token": adm.cookies.get("oppos_csrf") or ""}

# 1) admin integrations — using 'slug' key
r = adm.get(f"{BASE}/api/v1/admin/integrations", headers=adm_hdr, timeout=15)
ai = r.json()
providers = ai.get("providers", [])
slugs = {p.get("slug") for p in providers}
canonical = {"stripe","razorpay","paypal","paystack","google_auth","apple_auth",
             "email_password","resend","sendgrid","twilio","push_notifications",
             "openai","anthropic","gemini","elevenlabs","media_storage"}
valid_status = {"CONNECTED","TEST_MODE","CONFIGURATION_REQUIRED","DEGRADED","DISABLED"}
statuses = {p.get("status") for p in providers}
print(f"[admin_integrations_16] count={len(providers)} slugs_match={slugs==canonical} "
      f"missing={canonical-slugs} extra={slugs-canonical} statuses={statuses} "
      f"all_valid={statuses.issubset(valid_status)}")
# check no env value leak: for each provider, ensure only var names appear
# (heuristic: look for '=' followed by content in describe fields)

# 2) passport activation-status
r = fx.get(f"{BASE}/api/v1/passport/activation-status", headers=fx_hdr, timeout=15)
print(f"[passport_activation_status] status={r.status_code} keys={list(r.json().keys()) if r.status_code==200 else '-'}")

# 3) apple/status alternative — try apple/start (expect 503 when not configured)
r = requests.get(f"{BASE}/api/v1/auth/apple/start", timeout=15)
print(f"[apple_start_probe] status={r.status_code} body_snip={r.text[:200]}")
r2 = requests.get(f"{BASE}/api/v1/auth/apple/status", timeout=15)
print(f"[apple_status_probe] status={r2.status_code} body_snip={r2.text[:200]}")

# 4) webpush subscribe — correct payload shape (wrap in 'subscription')
r = requests.post(f"{BASE}/api/v1/notifications/subscribe",
                  headers=fx_hdr,
                  json={"subscription": {
                      "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
                      "keys": {"p256dh": "not-base-64-!!!!!", "auth": "not-base-64-!!!"}}},
                  timeout=15)
print(f"[webpush_malformed_b64] status={r.status_code} body={r.text[:300]}")

r = requests.post(f"{BASE}/api/v1/notifications/subscribe",
                  headers=fx_hdr,
                  json={"subscription": {
                      "endpoint": "ftp://x.example/y",
                      "keys": {"p256dh": "BOm3sB0" + "a"*80, "auth": "abcd"*5}}},
                  timeout=15)
print(f"[webpush_non_https] status={r.status_code} body={r.text[:300]}")
