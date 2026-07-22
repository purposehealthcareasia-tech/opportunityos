# OpportunityOS · Deployment Runbook

**Last updated:** 2026-02-21 (deployment-readiness final pass).
**Latest full backend regression:** **405 / 405 pytest green** (was 402 before
the malformed-subscription pruning regression added 3 tests).
**Frontend production build:** clean under `CI=true` — **171.81 kB gz main
bundle**, 7.14 kB gz CSS, zero lint errors.

This document is the authoritative operator handoff for taking OpportunityOS
from its current preview state to a real production environment.

---

## 1 · Preflight checklist (before flipping any prod flag)

Every item below must be true. Nothing here can be fixed by code — these are
operator/ops steps.

### 1.1 · Environment variables (production values, not committed)

| Var | Preview value | Production action | Fails fast? |
|---|---|---|---|
| `PROD_MODE` | `false` | Flip to `true` | Yes — combined with the CI issuer flag below |
| `CI_TEST_ISSUER_ENABLED` | `true` | Flip to `false` | Yes — `RuntimeError` at startup if both are true |
| `CORS_ALLOW_ORIGINS` | preview host + `http://localhost:3000` | Comma-separated exact prod origin(s) only. **No localhost.** In `PROD_MODE=true` loopback origins are automatically stripped by `server.py:150` even if provided | Yes — `RuntimeError` at startup if empty in prod |
| `JWT_SECRET` | 64-byte random present | **Rotate on deploy** to a fresh 64-byte value. Rotation invalidates all sessions, forcing users to re-login | No — but weak values silently break |
| `INTERNAL_SERVICE_TOKEN` | provisioned | **Rotate on deploy**. Used by internal `/api/internal/*` routes only. Not part of any user path | No — endpoints return 401/503 when unset |
| `MONGO_URL` | localhost | Point at the managed production MongoDB URI. Confirm the connection string carries a strong password | Motor raises at first query |
| `DB_NAME` | `opportunityos` | Set to the production database name | Same |
| `EMERGENT_LLM_KEY` | present | Confirm still set. Activates persistent Emergent object storage and AI provider TEST_MODE routing | No — falls back to local disk / config-required |
| `STORAGE_ROOT` | `/app/backend/storage` | Only used as fallback when `EMERGENT_LLM_KEY` is absent. Must resolve to a **persistent volume** in prod if you plan to rely on the local-disk fallback | No — silently loses data on container rebuild if pointed at ephemeral storage |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` | preview key pair present | Keep the preview VAPID pair or generate a fresh one via `py_vapid` **ONCE**. **Rotation invalidates all existing subscriptions** — do not rotate casually | No — Web Push provider reports `CONFIGURATION_REQUIRED` if any is missing/mailto |
| Vendor secrets (Stripe live, Apple `.p8`, Twilio, Resend, SendGrid, Razorpay, PayPal, Paystack, ElevenLabs) | absent | Provide only when activating the specific provider. Provider status flips automatically without code change | No — provider stays `CONFIGURATION_REQUIRED` |
| `BUILD_SHA` (optional) | unset | Set to the deployed commit SHA so `GET /api/v1/admin/health` reports it | No — falls back to `/app/.git/HEAD` |

### 1.2 · `.gitignore` hygiene

- `backend/.env` and `frontend/.env` are **intentionally NOT ignored**
  (fixed 2026-02-21). Emergent's deploy pipeline requires them present in
  the repo and rewrites them with production values on deploy.
- `.env.local` and `.env.*.local` are still ignored for ad-hoc local
  overrides.
- Never `git add` files containing real production secrets manually.

### 1.3 · Prod fail-fast guards (verified 2026-02-21)

```
PROD_MODE=true + CI_TEST_ISSUER_ENABLED=true         → RuntimeError at import
PROD_MODE=true + empty CORS_ALLOW_ORIGINS            → RuntimeError at import
PROD_MODE=true + CORS_ALLOW_ORIGINS=https://prod.x   → boots clean
```

---

## 2 · Deploy sequence

1. **Backend install & startup** — no code changes required. Supervisor is
   already configured. Fresh install:
   ```
   pip install -r /app/backend/requirements.txt
   supervisorctl restart backend
   ```
   Watch `/var/log/supervisor/backend.err.log` — a clean start emits
   `Seed complete: {..., 'prod_mode_seed_skipped': True, ...}` in `PROD_MODE=true`.

2. **Frontend build** — `CI=true yarn build` in `/app/frontend`. Produces
   `/app/frontend/build/` (~172 kB gz JS + 7 kB gz CSS). Serve as static
   assets behind ingress.

3. **DNS / ingress** — point production host at the pod. `/api/*` must
   route to backend port 8001; everything else to the frontend static
   bundle. Preview host and prod host must not share the same
   `REACT_APP_BACKEND_URL` — the frontend build embeds it at build time.

4. **Confirm health**:
   ```
   curl https://<prod-host>/api/health
   → {"ok": true, "mongo": true, "phase": 6, "policy_text_version": "1.0"}
   ```
   Public health MUST NOT expose `prod_mode` / `ci_test_issuer_enabled`
   (that's `/api/v1/admin/health`, admin-cookie gated).

5. **Admin-side sanity**: log in as an admin user (must be provisioned
   out-of-band in prod — the hardcoded-password seed accounts do NOT
   exist in `PROD_MODE=true`), then `GET /api/v1/admin/health`.
   Confirm `prod_mode: true`, `ci_test_issuer_enabled: false`,
   `build_sha` matches your deployed commit.

6. **Per-provider status probes** (public/lightweight, no auth):
   ```
   GET /api/v1/auth/apple/status         → {"configured": bool, "provider": "apple_auth"}
   GET /api/v1/auth/otp/status           → {"configured": bool, ...}
   GET /api/v1/notifications/vapid-public-key → {"ok": bool, "public_key": "..."}
   ```
   The admin-cookie-gated `GET /api/v1/admin/integrations` returns the
   authoritative status matrix for all 16 canonical providers.

7. **Fixture user (preview only)** — `fixture-ead@opportunityos.dev` and
   the two admin seed accounts are **not created** in `PROD_MODE=true`.
   Verify via
   `GET /api/v1/passport/activation-status` after a real user
   registration flow instead.

---

## 3 · Integration credential rollout

Per row status in the 16-integration audit (see `PRD.md` §
"📊 16-Integration Audit — CORRECTED"). Each `CONFIGURATION_REQUIRED`
row flips automatically once the env vars are set — no code deploy needed.

| Provider | Env vars to set | Webhook URL to register with vendor |
|---|---|---|
| Stripe (live) | `STRIPE_API_KEY` (live), `STRIPE_WEBHOOK_SECRET` | `/api/webhook/payment/stripe` |
| Razorpay | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | `/api/webhook/payment/razorpay` |
| PayPal | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `PAYPAL_ENV=live` | `/api/webhook/payment/paypal` |
| Paystack | `PAYSTACK_PUBLIC_KEY`, `PAYSTACK_SECRET_KEY`, `PAYSTACK_WEBHOOK_KEY` | `/api/webhook/payment/paystack` |
| Apple sign-in | `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY` (or path), `APPLE_REDIRECT_URI` (must be HTTPS + Apple-registered) | Apple Services ID → return URL |
| Resend | `RESEND_API_KEY`, `FROM_EMAIL`, `RESEND_WEBHOOK_SECRET` | `/api/webhook/email/resend` |
| SendGrid | `SENDGRID_API_KEY`, `FROM_EMAIL`, `SENDGRID_WEBHOOK_VERIFICATION_KEY` | `/api/webhook/email/sendgrid` |
| Twilio Verify | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID` | (no webhook — Verify only) |
| ElevenLabs | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID` | (no webhook) |
| Google sign-in | Emergent-managed handshake — no per-app secret | (no webhook — session-id exchange) |

Every provider's exact `missing_env` list is also visible in the admin
`Integrations` dashboard (`GET /api/v1/admin/integrations`). Web-facing
webhook URLs are surfaced per provider in the same dashboard.

---

## 4 · Human verification workflows

These items cannot be automated and MUST be performed by a human against
the real production environment before those rows can flip from
`HUMAN_VERIFICATION_REQUIRED` to `PRODUCTION_READY`.

### 4.1 · Google Sign-In click-through
1. Ensure the admin console shows `google_auth: CONNECTED`.
2. In a real browser at the prod host, open `/login`.
3. Click "Continue with Google". Confirm the redirect lands on
   `accounts.google.com`, choose a real Google account, grant scopes.
4. Confirm the browser redirects back to `/auth/callback`, the consent
   scopes screen renders, submit the five-scope consent.
5. Confirm `/passport` loads for the new account. Audit trail:
   `audit_logs` should contain `auth.google.completed` with the new user id.
6. Only after step 5 succeeds may the audit-report status flip from
   `HUMAN_VERIFICATION_REQUIRED` → `PRODUCTION_READY`.

### 4.2 · Web Push subscribe → grant → test-send → OS receipt
1. Log in as a normal user.
2. Open **Settings** and locate the Notifications section.
3. Click "Enable notifications". Browser must prompt for permission —
   grant it. Confirm the subscription is registered
   (`GET /api/v1/notifications/subscriptions` shows one active row).
4. Click "Send test notification". Confirm an OS-level push actually
   arrives on the device. Server response should be
   `{sent:1, failed:0, skipped:0, pruned:0}`.
5. Confirm `notifications.dispatched` appears in `audit_logs` with
   `sent:1`.
6. Only after step 4 succeeds may the audit-report status flip from
   `HUMAN_VERIFICATION_REQUIRED` → `PRODUCTION_READY`.

---

## 5 · Rollback / incident response

### 5.1 · Fast rollback
1. Redeploy the previous immutable image / commit SHA at the load
   balancer / ingress.
2. If MongoDB migrations were involved, restore from the most recent
   pre-deploy backup (see §5.3).
3. Force-invalidate all sessions by rotating `JWT_SECRET` again — every
   existing cookie will 401 on next request.

### 5.2 · Startup-failure clarity
The backend refuses to boot in these cases, with a clear message:
- `SECURITY: CI_TEST_ISSUER_ENABLED cannot be true in PROD_MODE=true`
- `SEC-004: PROD_MODE=true requires a non-empty CORS_ALLOW_ORIGINS`
- `Duplicate FastAPI operation IDs detected: ...`

Any other unhandled exception in lifespan is logged to
`/var/log/supervisor/backend.err.log` with a full traceback.
`GET /api/health` returns 200 as long as FastAPI is up, and
`{"mongo": false, ...}` if Mongo is unreachable.

### 5.3 · Backup / restore
- Managed MongoDB provider should be configured for daily point-in-time
  backups (retention ≥ 7 days). Verify before flipping `PROD_MODE`.
- Restore procedure is provider-specific; document the exact `mongorestore`
  command used, including the `--drop` flag if this is a full restore.
- The seeder is idempotent — running it after restore only touches
  reference data (`taxonomy`, `feature_flags`) in `PROD_MODE=true`.
- Emergent object storage is durable across container rebuilds; the
  `STORAGE_ROOT` local-disk fallback is NOT. If falling back to local
  disk in prod, it MUST live on a persistent volume.

---

## 6 · Ops observability signals

- **Public liveness**: `GET /api/health` → 200 with mongo status.
- **Admin readiness / build info**: `GET /api/v1/admin/health` →
  counts, LLM cost aggregate, deploy flags, `build_sha`.
- **Integration health**: `GET /api/v1/admin/integrations` →
  every provider's `status`, `missing_env`, `webhook_url`, last error.
- **Backend logs**: `/var/log/supervisor/backend.{err,out}.log`. All
  request logs go through Python's `logging` at INFO. `oppos.notifications`,
  `oppos.seeder`, `oppos.auth` are the primary domain loggers.
- **Correlation**: FastAPI attaches its default request id via
  `X-Request-ID` (client-provided) if present; every unhandled exception
  logs a full traceback with method + path.

---

## 7 · Final "must be true" checklist

Before flipping `PROD_MODE=true` for the first time:

- [ ] Managed production MongoDB with daily backups is reachable via
      `MONGO_URL`.
- [ ] `JWT_SECRET` and `INTERNAL_SERVICE_TOKEN` were rotated to fresh
      64-byte values for prod.
- [ ] `CORS_ALLOW_ORIGINS` contains ONLY the prod origin(s).
- [ ] A real admin account has been provisioned out-of-band. Confirm
      via `GET /api/v1/admin/health` that the account works.
- [ ] Vendor secrets that are being flipped live have been rotated to
      live-mode credentials (Stripe live key, Apple prod team, etc.).
- [ ] Webhook URLs registered with each vendor point at the prod host.
- [ ] Frontend `REACT_APP_BACKEND_URL` was set to the prod backend host
      **at build time** (not just runtime — CRA baked it in).
- [ ] `pytest tests/` passes on the built image
      (`405 / 405` reference figure — will grow with new tests).
- [ ] `CI=true yarn build` completes without errors.
- [ ] Google sign-in real click-through smoke test (§4.1) is planned
      as the FIRST post-deploy human check.
- [ ] Web Push subscribe + test-send smoke test (§4.2) is planned as
      the SECOND post-deploy human check.
