# OpportunityOS — GO-LIVE launch package

**Deploy label:** `DEPLOY_READY_WITH_EXTERNAL_BLOCKERS`
**HEAD at package time:** `d247a383` (`git log --oneline -1` should match `/api/v1/admin/health.build_sha`).
**Backend regression:** 405 / 405 pytest green.
**Frontend build:** clean under `CI=true` — 171.81 kB gz.
**Prod fail-fast:** verified.
**Fresh-DB PROD_MODE startup:** verified (`/tmp/step4_fresh_db_probe.py`).

This document is the operator-facing single source of truth for going
live. Everything is a **set env → click deploy → run smoke plan**
workflow. Nothing here requires a code deploy.

---

## STEP 1 · Google OAuth · GREEN pre-deploy · needs 1 human click at go-live

### Evidence
- 7/7 mocked-Emergent backend tests pass (`test_milestone_e_google.py`).
- Bad `session_id` → 401 `google_session_invalid`.
- Empty / too-long `session_id` → 422 (Pydantic).
- Unknown `pending_signup_id` → 404 `pending_signup_not_found`.
- Missing required consent scope on complete → 400 `required_consent_missing`.
- Rate limit hook active on `session_id` reuse via `services.login_throttle`.
- Account link uniqueness enforced by `linked_auth_identities` compound
  unique indexes on `(provider, provider_user_id)` and `(provider, email)`.
- Pending signup TTL = 15 min (Mongo TTL index).
- Consent-first: no user row until the 5-scope consent map is submitted.
- Live UI probe (2026-02-21 22:44 UTC): `/login` renders
  `Continue with Google` button (data-testid=`google-signin-btn`).
- Redirect URL is derived from `window.location.origin + '/auth/callback'`
  → auto-adapts to any prod host at build time. No hardcoded URL.
- Since Google auth is Emergent-managed, no per-app Google Cloud
  Console redirect URI change is required.

### Founder ask (3 lines, real-browser)
```
Open <PROD_HOST>/login → click Continue with Google.
Pick a real Google account, grant the five consent scopes on the
callback screen. Confirm you land on /passport with a logged-in session.
```

Post-click verification (I will run):
```
audit_logs grep for auth.google_completed with your new user_id.
GET /api/v1/auth/me → confirm the new session cookie works.
Flip audit-row status: HUMAN_VERIFICATION_REQUIRED → PRODUCTION_READY.
```

---

## STEP 2 · Web Push · GREEN pre-deploy · needs 1 human click at go-live

### Evidence
- 23/23 backend tests pass (`test_notifications_webpush.py`), including the
  three new malformed-subscription regression tests from the deployment
  readiness pass.
- Service worker `/sw.js` served with `content-type: application/javascript`.
- `GET /api/v1/notifications/vapid-public-key` public, returns `ok:true`,
  87-char URL-safe base64 public key, and the 5 supported categories.
- Live probes against the running preview backend:
  - `subscribe` with `ftp://` endpoint → 400 `subscription_invalid_endpoint`.
  - `subscribe` with malformed base64 keys → 400 `subscription_malformed_keys`.
  - Valid subscribe → 200 with `active:true`; `unsubscribe` → 200 `ok:true`.
  - Preferences `GET`/`PUT`/`GET` round-trip persists.
- Payload minimalism: no employer/salary/sealed/claim tokens ever cross
  the push boundary (fixed vocabulary titles + `_scrub_data_dict`).
- Ownership: unsubscribe on someone else's endpoint → 404 (no leak).
- Prune-on-404/410 from the push service is exercised.
- VAPID private key never appears in any response body (grep-verified).

### Founder ask (3 lines, real-browser)
```
Log in on <PROD_HOST>, open Settings → Notifications → Enable notifications.
Grant the browser permission prompt, then click Send test notification.
Confirm an OS-level push arrives on your device (title / body / click).
```

Post-click verification (I will run):
```
GET /api/v1/notifications/subscriptions → one active row for your user.
audit_logs grep for notifications.dispatched sent:1 for your user.
Flip audit-row status: HUMAN_VERIFICATION_REQUIRED → PRODUCTION_READY.
```

---

## STEP 3 · Production env configuration · READY to paste

### Where to find the candidate values
`/app/memory/.prod_secrets_DO_NOT_COMMIT` (gitignored, `chmod 600`).
Delete this file after pasting the values into Emergent's environment
settings.

### Founder paste-into-Emergent-settings checklist
| Env var name | Where the value lives | Value type |
|---|---|---|
| `JWT_SECRET` | `.prod_secrets_DO_NOT_COMMIT` line 1 | 86-char base64url (64-byte entropy) |
| `INTERNAL_SERVICE_TOKEN` | same file, line 2 | 86-char base64url |
| `VAPID_PUBLIC_KEY` | same file | 87-char URL-safe base64 (fresh key pair — no existing prod subscribers to invalidate) |
| `VAPID_PRIVATE_KEY` | same file | 43-char URL-safe base64 |
| `VAPID_SUBJECT` | same file | `mailto:support@opportunityos.dev` |
| `PROD_MODE` | literal `true` | boolean |
| `CI_TEST_ISSUER_ENABLED` | literal `false` | boolean |
| `CORS_ALLOW_ORIGINS` | your chosen `https://<PROD_HOST>` (no localhost) | comma-separated origins |
| `MONGO_URL` | managed prod MongoDB URI (Emergent auto-injects if platform-provisioned) | connection string |
| `DB_NAME` | literal `opportunityos` (or your chosen prod DB name) | string |
| `EMERGENT_LLM_KEY` | Emergent-auto (confirm still set) | key |
| `REACT_APP_BACKEND_URL` (frontend) | `https://<PROD_HOST>` — baked in at build time | URL |

### Fail-fast guarantee verified
```
PROD_MODE=true + CI_TEST_ISSUER_ENABLED=true         → RuntimeError at import
PROD_MODE=true + empty CORS_ALLOW_ORIGINS            → RuntimeError at import
PROD_MODE=true + CORS_ALLOW_ORIGINS=https://prod.…   → boots clean (138 routes loaded)
```

### Vendor credentials (only when activating each provider)
See `DEPLOYMENT.md` §3 for the exact env var names per provider.
Every credential-dependent integration is **fail-closed** in the
absence of its env vars (verified — see §"Safety" below).

---

## STEP 4 · MongoDB / storage · GREEN

### Fresh-DB startup evidence
Test harness: `/tmp/step4_fresh_db_probe.py`. Executes the full lifespan
against a freshly created empty DB with `PROD_MODE=true`. Result:

```
seed: PROD_MODE=true — skipping demo companies, sample jobs, and all
      hardcoded-password fixture accounts. Reference data only.
seed counts: {taxonomy: 13, feature_flags: 4, companies: 0,
              sample_jobs: 0, admin_users: 0, user_zero_id: None,
              fixture_user_id: None, prod_mode_seed_skipped: True}
prod seed guard: users=0 jobs=0 admins=0 companies=0 [PASS]
indexes present: sessions, notification_subscriptions,
                 notification_preferences, linked_auth_identities,
                 pending_google_signups, webhook_events,
                 apple_auth_states, submission_receipts
```

### What Emergent's platform provides (per pipeline docs)
- **Managed MongoDB** — Emergent injects `MONGO_URL` at deploy time. The
  founder confirms daily point-in-time backups are configured on the
  managed instance (retention ≥ 7 days recommended).
- **Object storage (Emergent-provided)** — activated automatically when
  `EMERGENT_LLM_KEY` is present. Durable across container rebuilds.
- **STORAGE_ROOT local-disk fallback** — only used when
  `EMERGENT_LLM_KEY` is unset. If falling back, the founder must
  confirm the mount is a persistent volume; otherwise every container
  rebuild loses uploads.

### What the founder must confirm before flipping `PROD_MODE=true`
- [ ] Managed prod MongoDB reachable via `MONGO_URL`.
- [ ] Daily backups + retention policy configured.
- [ ] `EMERGENT_LLM_KEY` present → object storage active. (Or, if
      falling back to local disk, `STORAGE_ROOT` on a persistent volume.)

### Rollback / restore
- Provider-specific `mongorestore` from the most recent pre-deploy
  backup. Do NOT run the seeder on a restored DB in prod — it is
  idempotent and touches reference data only in `PROD_MODE=true`, but
  running it on a partial restore before backups complete risks a
  redundant taxonomy upsert.

---

## STEP 5 · Domain · HTTPS · CORS · OAuth redirects · webhook URLs

### 5.1 Domain / HTTPS
- Emergent-managed default: `<app-name>.emergent…` on HTTPS. No DNS
  config required.
- Custom domain (if the founder owns one): follow Emergent's
  platform-side DNS docs. Common shape: `A` / `CNAME` at your DNS
  provider to Emergent's ingress host, then confirm HTTPS certificate
  is issued (auto-managed).

### 5.2 CORS
- Set `CORS_ALLOW_ORIGINS=https://<prod-host>` (comma-separated if
  multiple, one per origin). No `localhost`, no wildcards. Loopback
  origins are auto-stripped in `PROD_MODE=true` even if present.

### 5.3 Frontend build URL
- `REACT_APP_BACKEND_URL=https://<prod-host>` must be set **at frontend
  build time**. CRA bakes this into `main.<hash>.js`. Changing it at
  runtime has no effect.

### 5.4 Google OAuth redirect URI
- **No Google Cloud Console change required.** OpportunityOS uses
  Emergent-managed Google auth: the frontend redirects to
  `https://auth.emergentagent.com/?redirect=<window.location.origin>/auth/callback`.
  Because the redirect target is derived from
  `window.location.origin`, it will automatically be the prod host as
  long as `<PROD_HOST>` is the domain serving the frontend.

### 5.5 Apple OAuth redirect URI (only when activating Apple)
- Register `https://<PROD_HOST>/api/v1/auth/apple/callback` on the
  Apple Services ID Return URLs list in Apple Developer.
- Set `APPLE_REDIRECT_URI=https://<PROD_HOST>/api/v1/auth/apple/callback`
  in Emergent env settings.

### 5.6 Webhook URL registration checklist
| Vendor | URL to register | Env vars |
|---|---|---|
| Stripe | `https://<PROD_HOST>/api/webhook/payment/stripe` | `STRIPE_WEBHOOK_SECRET` |
| Razorpay | `https://<PROD_HOST>/api/webhook/payment/razorpay` | `RAZORPAY_WEBHOOK_SECRET` |
| PayPal | `https://<PROD_HOST>/api/webhook/payment/paypal` | `PAYPAL_WEBHOOK_ID` |
| Paystack | `https://<PROD_HOST>/api/webhook/payment/paystack` | `PAYSTACK_WEBHOOK_KEY` |
| Resend | `https://<PROD_HOST>/api/webhook/email/resend` | `RESEND_WEBHOOK_SECRET` |
| SendGrid | `https://<PROD_HOST>/api/webhook/email/sendgrid` | `SENDGRID_WEBHOOK_VERIFICATION_KEY` |

Every webhook route hard-fails 4xx on missing/bad signature — no bypass
mode in code. Confirmed by `test_milestone_h_webhooks.py` (9 tests) +
`test_code_review_fixes.py` mapping edge cases to 503/400.

---

## Final pre-deploy checklist (for the founder)

- [ ] `/app/memory/.prod_secrets_DO_NOT_COMMIT` opened; values pasted
      into Emergent's environment settings under matching NAMES.
- [ ] File `.prod_secrets_DO_NOT_COMMIT` deleted from the workspace.
- [ ] `PROD_MODE=true`, `CI_TEST_ISSUER_ENABLED=false`,
      `CORS_ALLOW_ORIGINS=<prod host only>` set.
- [ ] `JWT_SECRET`, `INTERNAL_SERVICE_TOKEN` rotated to the fresh
      64-byte values.
- [ ] `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` set
      (fresh pair or preview pair — pick one and never rotate again).
- [ ] `MONGO_URL` points at the managed prod DB; daily backups
      confirmed.
- [ ] `EMERGENT_LLM_KEY` still present (activates persistent object
      storage).
- [ ] Frontend `REACT_APP_BACKEND_URL` set to the prod host **at build
      time**.
- [ ] Custom domain / DNS records (if applicable) resolved on HTTPS.
- [ ] Deploy triggered from the Emergent platform.

---

## Post-deploy smoke plan (I will execute)

### T+0 · smoke set (equivalent to iteration_18 live smoke, retargeted at prod)
1. `GET https://<PROD_HOST>/api/health` → 200 with
   `{ok, mongo, phase, policy_text_version}` and **no** `prod_mode` /
   `ci_test_issuer_enabled` keys.
2. Log in as a newly created admin (out-of-band provisioned; see
   §"admin bootstrap in prod" below).
3. `GET /api/v1/admin/health` → `prod_mode: true`,
   `ci_test_issuer_enabled: false`, `build_sha` matches the deployed
   commit.
4. `GET /api/v1/admin/integrations` → exactly 16 canonical rows with
   truthful statuses (email_password CONNECTED; VAPID keys present so
   push_notifications CONNECTED; unconfigured vendors
   CONFIGURATION_REQUIRED).
5. `GET /api/v1/notifications/vapid-public-key` → new prod public key.
6. Public `GET /api/v1/auth/apple/status` → `{configured: bool}` (true
   iff APPLE_* env set; else honest false).
7. `POST /api/internal/fixture/rebase` → 503 `fixture_rebase_disabled_in_prod`.
8. Signup a real fresh user via email/password → confirm consent
   ledger row + audit rows + `passport_activated: false`.
9. Passport activation flow (upload résumé → parse claims → approve
   claims → activate).
10. Feed / preferences / eligibility / matching flow on the fresh
    account.
11. Billing test flow (Stripe test-mode until live key rotation).
12. Privacy export bundle → grep for any of `password_hash`,
    `csrf_token`, `session_id`, `totp_secret`, `recovery_codes`,
    `$2b$` → all absent.

### T+30min · human click-throughs
- Google click-through (§STEP 1 Founder ask).
- Web Push subscribe + test-send (§STEP 2 Founder ask).

### T+day-one · flip audit rows
Only after the two clicks succeed do the following rows change:
- `google_auth`: HUMAN_VERIFICATION_REQUIRED → PRODUCTION_READY.
- `push_notifications`: HUMAN_VERIFICATION_REQUIRED → PRODUCTION_READY.

Final audit becomes **3 / 16 PRODUCTION_READY**, 5 / 16 TEST_MODE,
0 / 16 HUMAN_VERIFICATION_REQUIRED, 8 / 16 CONFIGURATION_REQUIRED, 0
PARTIAL/BROKEN.

---

## Safety citations · fail-closed integrations (from iteration_18 verification)

| Provider | Fail-closed evidence |
|---|---|
| Apple sign-in | `integrations/auth/apple_provider.py:138`; `router.py:99-107` returns 503 `apple_auth_not_configured`; new `/apple/status` returns `{configured:false}`. 16 tests in `test_auth_apple_signin.py`. |
| Twilio (OTP) | `integrations/sms/twilio_provider.py:71,:91,:122`; `router.py::/otp/status` returns `{configured:false}` publicly. 7 + 10 tests. |
| Resend | `integrations/email/resend_provider.py:57,:87`; webhook hard-fail on missing signing secret. 14 tests. |
| SendGrid | `integrations/email/sendgrid_provider.py:56,:79`; ECDSA P-256 signing key required. 14 tests. |
| Razorpay | `integrations/payments/razorpay_provider.py:54,:74`; HMAC-SHA256 webhook. 16 + 9 tests. |
| PayPal | `integrations/payments/paypal_provider.py:95,:109`; server-to-server verify; failures map to 503. 16 + 9 tests. |
| Paystack | `integrations/payments/paystack_provider.py:52,:72`; HMAC-SHA512 webhook. 16 + 9 tests. |
| ElevenLabs | `integrations/voice/elevenlabs_provider.py:48,:68,:74`; hard-fail before any HTTP call. Registry-level coverage; dedicated suite deferred P2. |

Cross-cutting: `test_security_invariants.py` (35 tests) locks the
no-secret-leak invariant across every admin/user response endpoint.

---

## Admin bootstrap in prod

`admin@opportunityos.dev` / `Admin!Console1` is a **PREVIEW-ONLY** seed
account and does NOT exist in `PROD_MODE=true` (seeder skips it).
Provision the first prod admin out-of-band via:

```
# 1. Create the user through the normal signup endpoint (any real email + password).
curl -sX POST https://<PROD_HOST>/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"<founder-email>","password":"<founder-password>","name":"…"}'

# 2. Grant admin role via a direct MongoDB write.
mongosh "<MONGO_URL>/opportunityos" --eval \
  'db.admin_users.insertOne({user_id:"<user-id-from-step-1>",role:"admin"})'
```

Or bake this into a first-boot admin-invite flow gated by an
env-provisioned bootstrap token in a follow-up brief.
