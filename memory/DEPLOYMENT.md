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


---

## 7 · Platform CORS injection on preview subdomains (2026-02-21)

### Symptom

An independent tester probing the public **preview** URL
(`https://<slug>.preview.emergentagent.com`) observed:

```
GET /api/health   Origin: https://evil.example.com
→ 200
   server: cloudflare
   access-control-allow-origin: *              ← unexpected
   access-control-allow-credentials: true      ← app-emitted
   access-control-allow-headers: *             ← unexpected
   access-control-allow-methods: GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH
   access-control-max-age: 300                 ← app default is 600
   access-control-expose-headers: X-Idempotent-Replay
```

The `ACAO: *` combined with `access-control-allow-credentials: true` is
CORS-spec illegal — browsers must reject any credentialed response with a
wildcard origin — and looks alarming.

### Root cause: platform ingress, NOT the app

Reproducer (2026-02-21, HEAD `b74d7185`):

- Direct `curl -H "Origin: https://evil.example.com" http://localhost:8001/api/health`
  → returns **only** the app headers (`access-control-allow-credentials: true`,
  `access-control-expose-headers: X-Idempotent-Replay`). **No** `ACAO`, no
  `allow-headers`, no `allow-methods`, no `max-age`. The app correctly
  refuses to echo an unlisted origin.
- Same request through the public preview URL adds a permissive envelope
  (`ACAO: *`, `access-control-allow-headers: *`, `access-control-max-age:
  300`, `x-robots-tag: noindex, nofollow`, `server: cloudflare`). The
  method list order (`GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH`)
  differs from Starlette's alphabetical order (`DELETE, GET, HEAD, OPTIONS,
  PATCH, POST, PUT`) which the app returns on `/api/v1/*` endpoints. That
  ordering delta plus the `max-age: 300` (vs app default 600) confirms the
  extra headers are appended by the preview edge (Cloudflare ingress), not
  by the FastAPI process.

The app CORS configuration is standards-clean:

- `server.py:150–164` — with `CORS_ALLOW_ORIGINS` populated, the middleware
  uses `allow_origins=<the exact list>` and `allow_credentials=True`. Never
  a wildcard alongside credentials.
- `server.py:165–181` — the empty-allowlist dev fallback uses
  `allow_origins=["*"]` but **with `allow_credentials=False`**, which is
  the only legal wildcard configuration.
- `server.py:169–173` — `PROD_MODE=true` with an empty allowlist refuses
  to start (`RuntimeError`).

### Production evidence (2026-02-21, `https://fynd.llc`)

The same hostile-origin probes against the custom-domain production host:

```
GET  /api/health, Origin: https://evil.example.com
→ 200, server: cloudflare
   access-control-allow-credentials: true
   access-control-expose-headers: X-Idempotent-Replay
   x-content-type-options: nosniff
   (no access-control-allow-origin — CORRECT app behavior echoed through)

OPTIONS /api/v1/auth/me, Origin: https://evil.example.com,
     Access-Control-Request-Method: GET
→ 400, server: cloudflare
   vary: Origin
   access-control-allow-credentials: true
   access-control-allow-methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT
   access-control-max-age: 600     ← app default, NOT 300
   x-content-type-options: nosniff
   (no access-control-allow-origin — CORRECT)
```

Prod is behind the same Cloudflare edge but the wildcard CORS envelope is
**NOT** injected for the custom domain. So this is specifically a
`*.preview.emergentagent.com` ingress default, not a global Emergent
behavior. Prod runtime enforces app-level CORS unchanged.

### Residual-risk assessment on the preview URL

Even with `ACAO: *` present on preview responses, the observable browser
behavior is:

1. `fetch(preview, {credentials: 'include'})` — the browser sees `ACAO: *`
   in the response and per CORS spec REFUSES to deliver the response body
   to the JavaScript caller (credentialed responses require an exact-origin
   echo). Cookies are never exfiltrated. **No credential leak.**
2. `fetch(preview, {credentials: 'omit'})` — the browser accepts the
   response, but the request carried no cookie / no session, so the caller
   sees only what an anonymous public request would see. On this app that
   is limited to `/api/health`, `/api/v1/meta/policy`,
   `/api/v1/notifications/vapid-public-key`, `/api/v1/auth/apple/status`
   and `/api/v1/auth/otp/status` — all intentionally public.
3. State-changing requests (`POST`/`PUT`/`PATCH`/`DELETE`) are gated by the
   `CSRFMiddleware` double-submit cookie. A cross-origin browser attacker
   cannot read the CSRF cookie (SameSite + no credentialed response
   delivery) and therefore cannot forge the header.
4. Idempotency middleware still requires an `Idempotency-Key` header on
   the writes that use it; the wildcard preflight doesn't grant the
   attacker the ability to read replay tokens.

**Net:** the wildcard injection is cosmetic on preview and does not weaken
the authenticated data plane. It is worth removing to keep preview
security signalling honest, but there is no action the app can take —
Emergent Platform Support owns the preview ingress config.

### Action items

- **App-level:** none. Code is standards-compliant.
- **Platform ticket (post-launch):** ask Emergent Platform Support to stop
  appending `ACAO: *` + wildcard `allow-headers` on `*.preview.emergentagent.com`
  responses, so preview honors the same origin-allowlist behavior the app
  actually implements. Reference this document.
- **Documentation:** this section (§7) IS the finding. Do not treat the
  preview wildcard as a production regression — production evidence above
  confirms it does not propagate to custom domains.

### Verification recipe

```bash
# App is clean (should show NO access-control-allow-origin)
curl -sI -H "Origin: https://evil.example.com" http://localhost:8001/api/health \
  | grep -i access-control

# Preview shows the platform-injected wildcard (documented behavior)
curl -sI -H "Origin: https://evil.example.com" \
  https://<slug>.preview.emergentagent.com/api/health | grep -i access-control

# Prod echoes only app CORS (no wildcard)
curl -sI -H "Origin: https://evil.example.com" https://fynd.llc/api/health \
  | grep -i access-control
```

### 7.1 · Escalation (2026-07-24) — edge OVERWRITES app-emitted exact-origin echo

Follow-up forensics while adding the Expo web preview origin
`https://lynk-preview-2.expo.preview.emergentagent.com` to the workspace
`CORS_ALLOW_ORIGINS` allowlist upgraded the earlier finding. The preview
edge does not merely inject a wildcard onto CORS-header-less responses —
**it overwrites an app-emitted exact-origin `Access-Control-Allow-Origin`
header with `*`** and strips `Access-Control-Allow-Credentials` from the
OPTIONS preflight response entirely.

**Setup:** `CORS_ALLOW_ORIGINS` (workspace, preview-safe) contains four
origins including the Expo web preview host. Backend restarted; running
process view confirms `CORS_ORIGINS_COUNT=4`.

**Direct-loopback probe (`http://localhost:8001`), `Origin:
https://lynk-preview-2.expo.preview.emergentagent.com`:**

```
OPTIONS /api/v1/auth/login
→ HTTP/1.1 200
  vary: Origin
  access-control-allow-origin: https://lynk-preview-2.expo.preview.emergentagent.com
  access-control-allow-credentials: true
  access-control-allow-methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT
  access-control-allow-headers: content-type,x-csrf-token
  access-control-max-age: 600

GET /api/health
→ HTTP/1.1 200
  vary: Origin
  access-control-allow-origin: https://lynk-preview-2.expo.preview.emergentagent.com
  access-control-allow-credentials: true
  access-control-expose-headers: X-Idempotent-Replay

POST /api/v1/auth/login  (invalid body → 422; headers preserved)
→ HTTP/1.1 422
  vary: Origin
  access-control-allow-origin: https://lynk-preview-2.expo.preview.emergentagent.com
  access-control-allow-credentials: true
  access-control-expose-headers: X-Idempotent-Replay
```

App CORS behavior is standards-clean: exact-origin echo for the
allowlisted origin, credentials header present on both the preflight and
the actual response.

**Public preview edge (`https://lynk-preview-2.preview.emergentagent.com`),
identical `Origin`:**

```
OPTIONS /api/v1/auth/login
→ HTTP/2 204
  server: cloudflare
  access-control-allow-origin: *                                  ← WILDCARD OVERWRITE
  access-control-allow-headers: *
  access-control-allow-methods: GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH
  access-control-max-age: 300
  (access-control-allow-credentials — HEADER STRIPPED)

GET /api/health
→ HTTP/2 200
  server: cloudflare
  access-control-allow-origin: *                                  ← WILDCARD OVERWRITE
  access-control-allow-credentials: true                          ← spec-invalid with `*`
  access-control-allow-headers: *
  access-control-allow-methods: GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH
  access-control-max-age: 300

POST /api/v1/auth/login  (invalid body → 422)
→ HTTP/2 422
  server: cloudflare
  access-control-allow-origin: *                                  ← WILDCARD OVERWRITE
  access-control-allow-credentials: true                          ← spec-invalid with `*`
  access-control-allow-headers: *
  access-control-allow-methods: GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH
  access-control-max-age: 300
  set-cookie: __cf_bm=<REDACTED>; ...                             ← Cloudflare bot cookie, not app session
```

Fingerprints proving the rewrite is edge-side (Cloudflare) and not the
app:
- `access-control-allow-origin` changes from the exact allowlisted origin
  to `*`.
- `access-control-allow-methods` is reordered from Starlette's
  alphabetical `DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT` to Cloudflare's
  functional `GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH`.
- `access-control-max-age` drops from the app's `600` to `300`.
- `access-control-allow-headers` becomes `*` regardless of the
  `Access-Control-Request-Headers` value the app echoed.
- `access-control-allow-credentials` disappears from OPTIONS preflight
  responses but stays present on the actual GET/POST response.
- `server: cloudflare` present.

### 7.2 · Consequence (CORS spec walk-through)

1. Browser sends `OPTIONS` preflight before any credentialed cross-origin
   POST. Edge returns `ACAO: *` **without** `access-control-allow-credentials`.
   Per spec, a credentialed follow-up requires *both* an exact-origin
   echo AND `access-control-allow-credentials: true` on the preflight.
   The browser therefore **cancels the follow-up credentialed request
   before it is sent** and reports a CORS failure.
2. For simple credentialed GETs (`credentials: 'include'`), the response
   has `ACAO: *` alongside `access-control-allow-credentials: true` —
   spec-invalid. The browser refuses to deliver the body to the caller
   and refuses to store any `Set-Cookie`.
3. Native mobile runtimes (Expo native builds, iOS/Android HTTP clients)
   **do not enforce CORS**. They succeed against this backend regardless
   of edge headers. Native Expo devices are therefore unaffected by this
   issue.

### 7.3 · Impact scope

- Browser Expo web preview → preview backend: **blocked cross-origin for
  credentialed auth.**
- Same-origin SPA in preview (`lynk-preview-2.preview.emergentagent.com`
  → same backend): **unaffected** (no cross-origin, no preflight
  required).
- Native mobile → preview backend: **unaffected.**
- Any surface → production `https://fynd.llc`: **unaffected**; production
  custom domain on the same Cloudflare edge does NOT exhibit the
  overwrite (verified in §7 initial probe with hostile origin).

### 7.4 · Action items (revised)

- **App-level:** none. `server.py:150–164` is standards-clean and now
  proven to emit correct exact-origin + credentials headers for the
  allowlisted Expo web origin.
- **Platform ticket (upgraded severity):** ask Emergent Platform Support
  to **stop rewriting CORS response headers on `*.preview.emergentagent.com`**.
  Preview should honor app-emitted CORS headers verbatim. The wildcard
  overwrite blocks any browser-based credentialed cross-origin
  authentication to preview subdomains — the exact scenario needed to
  test the Expo web build.
- **Testing:** until the platform fix lands, mobile Phase 1 browser-based
  auth verification must use native Expo builds (or a same-origin proxy),
  not the Expo Web preview host through the preview edge.

