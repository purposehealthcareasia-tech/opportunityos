# OpportunityOS — Product Requirements (living)

**Codename in repo:** LYNK.
**Web-first.** Backend: FastAPI @ 8001. Frontend: React @ 3000. DB: MongoDB. Ingress: all backend under `/api/*`.

---

## 🚀 Deployment-Readiness — FINAL PASS (2026-02-21)

**Label: `DEPLOY_READY_WITH_EXTERNAL_BLOCKERS`.**

The code, build, tests, config, and startup guards are all verified. What
remains is external — production credentials, DNS, vendor webhook
registrations, and two human click-through smoke tests. Nothing else in
this repo can turn those into `PRODUCTION_READY` on its own.

**Fresh HEAD SHA at end of pass:** see `git log --oneline -1`.
**Backend regression:** **405 / 405 pytest green** (was 402; +3 new
malformed-subscription pruning tests).
**Frontend production build:** clean under `CI=true` —
**171.81 kB gz** main bundle, **7.14 kB gz** CSS, zero lint errors.
**Prod fail-fast:** verified — server refuses to boot on
`PROD_MODE=true + CI_TEST_ISSUER_ENABLED=true` and on
`PROD_MODE=true + empty CORS_ALLOW_ORIGINS`, boots clean with a valid
prod origin.

### What was fixed this pass
1. **P0 · deployment blocker** — `.gitignore` was blocking `backend/.env`
   and `frontend/.env`. Emergent's deploy pipeline requires those files
   present in the repo so it can overwrite them with production values on
   deploy. `.gitignore` now permits them and keeps only `.env.local` /
   `.env.*.local` ignored. Detected by `deployment_agent` static scan.
2. **P0 · real runtime bug** — Web-push dispatch crashed with
   `binascii.Error` on a malformed `p256dh` / `auth`. Prior tests mocked
   `pywebpush` and never exercised this path, so it slipped through.
   Fixed in two places:
   - `register_subscription()` now rejects non-urlsafe-base64 keys and
     non-`https://` endpoints with `400 subscription_malformed_keys` /
     `subscription_invalid_endpoint` before anything is stored.
   - `dispatch()` now catches `ValueError` / `TypeError` (which is what
     `binascii.Error` inherits) and prunes the offending subscription
     with `prune_reason=malformed_subscription:<type>`, so a legacy bad
     row never causes repeat 500-log noise.
   - New tests: `TestSubscriptionLifecycle::test_register_rejects_malformed_base64_keys`,
     `TestSubscriptionLifecycle::test_register_rejects_non_https_endpoint`,
     `TestMalformedSubscriptionPruning::test_pywebpush_binascii_error_prunes_subscription`.
3. **Frontend lint** — 15 unused-import warnings across 9 pages that
   would break a strict `CI=true` build. Removed. Production build now
   clean under CI mode.
4. **Ops observability** — `GET /api/v1/admin/health` now returns
   `build_sha` (from `BUILD_SHA` env var if set, else `/app/.git/HEAD`)
   so operators can confirm which commit is actually running in a pod.
5. **New operator handoff doc** — `/app/memory/DEPLOYMENT.md` — full
   preflight checklist, prod fail-fast reference, deploy sequence,
   credential rollout table (per provider + exact webhook URL),
   human-verification workflows (Google + Web Push), rollback /
   incident procedures, observability signals, final go-live checklist.

### Remaining external blockers (nothing more can be done in-repo)
- Real Google OAuth click-through smoke test in a real browser.
- Real Web Push subscribe + test-send + OS-receipt smoke test in a real
  browser.
- Apple Developer credentials (`APPLE_CLIENT_ID`, `APPLE_TEAM_ID`,
  `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`, `APPLE_REDIRECT_URI`).
- Twilio Verify credentials (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
  `TWILIO_VERIFY_SERVICE_SID`).
- Resend / SendGrid / Razorpay / PayPal / Paystack / ElevenLabs
  credentials (see `DEPLOYMENT.md` §3 for the exact env var names).
- Stripe live-mode key rotation (currently `TEST_MODE` on the shared
  Emergent Stripe test key).
- Managed production MongoDB URL with daily backups configured.
- `CORS_ALLOW_ORIGINS` set to the prod origin (loopback is auto-stripped
  in `PROD_MODE=true`).
- `JWT_SECRET` and `INTERNAL_SERVICE_TOKEN` rotated to fresh 64-byte
  values for prod.
- Persistent-volume mount confirmed if relying on the local-disk storage
  fallback (Emergent object storage is durable; local disk in a
  fresh container is not).

---

## 📊 16-Integration Audit — CORRECTED (2026-02-21)

**HEAD SHA at audit time:** `c3df1f54` (`git log --oneline -1`).

**Provider registry / Admin Integrations dashboard is INFRASTRUCTURE and is
NOT counted here.** The 16 rows below correspond one-to-one with the
founder's canonical panel list.

**Taxonomy (one per row):**
- `PRODUCTION_READY` — fully working end-to-end, no pending human step, no prod-flag caveat.
- `TEST_MODE` — working on test/platform credentials (Stripe test key, Emergent LLM key, Emergent storage).
- `HUMAN_VERIFICATION_REQUIRED` — code CONNECTED but the final real-world step needs a human.
- `CONFIGURATION_REQUIRED` — code complete; awaiting founder credentials.
- `PARTIAL` / `BROKEN` — not applicable to any row this pass.

Live registry statuses observed at audit time (via `registry.load_all()` + `prov.status()`):
`stripe→TEST_MODE`, `google_auth→CONNECTED`, `apple_auth→CONFIGURATION_REQUIRED`,
`email_password→CONNECTED`, `resend→CONFIGURATION_REQUIRED`, `sendgrid→CONFIGURATION_REQUIRED`,
`twilio→CONFIGURATION_REQUIRED`, `openai→TEST_MODE`, `anthropic→TEST_MODE`,
`gemini→TEST_MODE`, `elevenlabs→CONFIGURATION_REQUIRED`, `media_storage→TEST_MODE`,
`razorpay→CONFIGURATION_REQUIRED`, `paypal→CONFIGURATION_REQUIRED`,
`paystack→CONFIGURATION_REQUIRED`, `push_notifications→CONNECTED`.

| # | Integration | **Status (corrected)** | Test evidence (file · count · latest suite) | Required env vars (names only) | Commit SHA covering this integration |
|---|---|---|---|---|---|
| 1 | **Stripe** | `TEST_MODE` | `test_milestone_f_payments.py` — 16 tests (signature verify + status matrix). Latest suite: 402/402 green (`/tmp/regression_final2.log`). | `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET` (env-provisioned test key already present) | `5d03be0b` (provider) · `3460a71d` (webhook router + code-review remediation) |
| 2 | **Razorpay** | `CONFIGURATION_REQUIRED` | `test_milestone_f_payments.py` (signature suite includes Razorpay HMAC), `test_milestone_h_webhooks.py` — 9 tests, `test_code_review_fixes.py` — 8 tests. | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | `5d03be0b` (provider + lifecycle-aware dedup) |
| 3 | **PayPal** | `CONFIGURATION_REQUIRED` | Same suites as Razorpay (`test_milestone_f_payments.py` includes PayPal webhook hard-fail + `test_milestone_h_webhooks.py`). | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `PAYPAL_ENV` | `5d03be0b` · `3460a71d` (503 mapping for verify failures) |
| 4 | **Paystack** | `CONFIGURATION_REQUIRED` | `test_milestone_f_payments.py` (Paystack signature verify class), `test_milestone_h_webhooks.py`. | `PAYSTACK_PUBLIC_KEY`, `PAYSTACK_SECRET_KEY`, `PAYSTACK_WEBHOOK_KEY` | `5d03be0b` |
| 5 | **Emergent-managed Google sign-in** | `HUMAN_VERIFICATION_REQUIRED` — backend + frontend both CONNECTED; end-to-end sign-in requires a real Google account click-through | `test_milestone_e_google.py` — 7 tests (mocked Emergent session-id endpoint via httpx.MockTransport). Latest suite 402/402 green. | Emergent-managed handshake (no user-provided key) | `5d03be0b` (provider + service) |
| 6 | **Sign in with Apple** | `CONFIGURATION_REQUIRED` | `test_auth_apple_signin.py` — 16 tests (bad signature / nonce / kid / audience / expired / relay-email / duplicate-sub / describe-never-leaks). Latest suite 402/402 green. | `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`, `APPLE_REDIRECT_URI` | `c3df1f54` (provider + service + router + Login button) |
| 7 | **Email & password** | **`PRODUCTION_READY`** | `test_security_invariants.py` — 35 tests · `test_iteration14_advisory_fix.py` — 22 · `test_iteration15_advisory_fix_hardened.py` — 19 · Registration/login coverage in `test_milestone_a_integrations.py` — 23 · `test_code_review_fixes.py` — 8. Latest suite 402/402 green. | `JWT_SECRET`, `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE` (all env-provisioned) | `26518118` (provider) · `ea53e8d5` (service) |
| 8 | **Resend** | `CONFIGURATION_REQUIRED` | `test_milestone_c_email.py` — 14 tests · `test_milestone_h_webhooks.py` — 9. | `RESEND_API_KEY`, `FROM_EMAIL`, `RESEND_WEBHOOK_SECRET` | `5d03be0b` |
| 9 | **SendGrid** | `CONFIGURATION_REQUIRED` | `test_milestone_c_email.py` — 14 · `test_milestone_h_webhooks.py` — 9 · `test_code_review_fixes.py` (503 mapping for verification key misuse). | `SENDGRID_API_KEY`, `FROM_EMAIL`, `SENDGRID_WEBHOOK_VERIFICATION_KEY` | `5d03be0b` (provider) · `3460a71d` (code-review 503 mapping) |
| 10 | **Twilio (phone verification codes) + OTP login** | `CONFIGURATION_REQUIRED` | `test_milestone_d_twilio.py` — 7 tests (adapter) · `test_auth_otp_login.py` — 10 tests (login/attach flow, 503-when-not-configured, phone-normalization, no-account-for-phone, incorrect-code, duplicate-attach). Latest suite 402/402 green. | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID` | `5d03be0b` (provider) · `c3df1f54` (OTP service + Login UI) |
| 11 | **Push notifications** | `HUMAN_VERIFICATION_REQUIRED` — VAPID key pair present in preview env, provider is CONNECTED; real end-to-end delivery requires a browser to actually subscribe and receive a push (backend tests mock `pywebpush`) | `test_notifications_webpush.py` — 20 tests (payload minimalism, ownership rejection, opt-out enforcement, dedup, prune-on-404/410, provider status transitions, describe-never-leaks). Latest suite 402/402 green. **Playbook finding cited:** Emergent-managed push is Expo/mobile-only → NOT_APPLICABLE (web); shipped standards-based VAPID as the compliant alternative. | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (generated ONCE, never rotated casually — regeneration invalidates existing subscriptions) | `c3df1f54` |
| 12 | **OpenAI Chat Models** | `TEST_MODE` (Emergent LLM Key) | `test_milestone_g_ai_gateway.py` — 5 tests. | Emergent LLM Key (universal, env-provisioned) | `5d03be0b` |
| 13 | **Anthropic Chat Models** | `TEST_MODE` (Emergent LLM Key) | `test_milestone_g_ai_gateway.py` — 5 tests. | Emergent LLM Key (universal) | `5d03be0b` |
| 14 | **Gemini Chat Models** | `TEST_MODE` (Emergent LLM Key) | `test_milestone_g_ai_gateway.py` — 5 tests. | Emergent LLM Key (universal) | `5d03be0b` |
| 15 | **ElevenLabs** | `CONFIGURATION_REQUIRED` — HONEST GAP: no dedicated test file. Registry-level coverage only via `test_milestone_a_integrations.py` (slug-list, status truthfulness) and `test_iteration14/15_advisory_fix*` (dashboard payload shape). No `webpush`-style dedicated suite exists yet. This does not affect the CONFIGURATION_REQUIRED status truthfulness, but a dedicated `test_milestone_j_voice.py` is a legitimate P2 follow-up. **My earlier PRD claimed such a file existed — it does not.** | `test_milestone_a_integrations.py` (elevenlabs slug + status), `test_iteration14_advisory_fix.py`, `test_iteration15_advisory_fix_hardened.py`. | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID` | `5d03be0b` |
| 16 | **File & media storage** | `TEST_MODE` (Emergent object storage selected via `EMERGENT_LLM_KEY`; local-disk fallback for dev) | `test_milestone_b_storage.py` — 4 tests (backend selection, round-trip, describe-never-leaks, live-backend probe). | `EMERGENT_LLM_KEY` (auto-provisioned) — falls back to `STORAGE_ROOT` local disk if absent | `5d03be0b` |

### Corrected totals

**1 / 16 `PRODUCTION_READY`** · Email & password (row 7).
**5 / 16 `TEST_MODE`** · Stripe (1), OpenAI (12), Anthropic (13), Gemini (14), File & media storage (16).
**2 / 16 `HUMAN_VERIFICATION_REQUIRED`** · Emergent Google sign-in (5), Push notifications (11).
**8 / 16 `CONFIGURATION_REQUIRED`** · Razorpay (2), PayPal (3), Paystack (4), Apple sign-in (6), Resend (8), SendGrid (9), Twilio+OTP (10), ElevenLabs (15).
**0 / 16 `PARTIAL` or `BROKEN`.**

*This matches the founder's expected recount exactly.*

### Honesty callouts

1. **ElevenLabs test coverage gap.** My earlier PRD referenced `test_milestone_j_voice.py`. That file does not exist. ElevenLabs is currently exercised only through registry-level tests (`test_milestone_a_integrations.py` and the iteration14/15 audit-payload suites). CONFIGURATION_REQUIRED status is still truthful because the provider correctly reports it, but a dedicated ElevenLabs test suite is a legitimate P2 follow-up.
2. **Push notifications status = `HUMAN_VERIFICATION_REQUIRED`, not `PRODUCTION_READY`.** VAPID keys + provider + Service Worker + Settings UI + full backend flow are all in place, and every backend path is unit-tested against a mocked `pywebpush`. But a real push delivered to a real device requires a browser to subscribe first — no automation can produce that evidence.
3. **Emergent-managed Google sign-in status = `HUMAN_VERIFICATION_REQUIRED`.** Session-id handshake is fully working and unit-tested with mocked Emergent responses; end-to-end verification requires a human clicking "Continue with Google" on a real browser.
4. **Stripe is TEST_MODE, not PRODUCTION_READY.** The env-provisioned key is a test-mode key. Flipping to live mode is a deploy-time key rotation and remains founder-side.

### HEAD SHA

`git log --oneline -1` at audit time → **`c3df1f54`**.

---

## 🚦 Deployment Readiness — READY WITH DEPLOY-TIME CONFIG (2026-02-21)

Independent verification: `/app/test_reports/iteration_17.json` — 6/6 items
GREEN, `retest_needed=false`, zero action_items. Full backend regression
**402 / 402** pytest green.

### Status per audit category
- **Services / supervisor:** READY. `backend`, `frontend`, `mongodb`,
  `nginx-code-proxy`, `webhook-crond` RUNNING. (`code-server` STOPPED and
  `mobile` FATAL are unrelated container services, not app blockers.)
- **Ingress / `/api` routing:** READY. All app routes prefixed `/api`.
  The only non-`/api` route is FastAPI's built-in `/docs/oauth2-redirect`
  helper (docs served at `/api/docs`).
- **Frontend env handling:** READY. `src/lib/api.js` binds `baseURL` to
  `process.env.REACT_APP_BACKEND_URL`; no hardcoded backend URLs.
- **Secrets / `.env` git hygiene:** READY. `.gitignore` excludes
  `backend/.env` + `frontend/.env` explicitly; both files confirmed
  untracked via `git ls-files`.
- **Deploy-hostile paths:** READY. No hardcoded `localhost`/`127.0.0.1`
  in runtime backend code (only in a comment and the pydantic-settings
  MONGO_URL *default*, which is env-overridden). Frontend has zero
  hardcoded backend origins. `STORAGE_ROOT` default is `/app/backend/
  storage` (local-disk fallback only — Emergent object storage kicks in
  automatically when `EMERGENT_LLM_KEY` is set).
- **MongoDB — indexes / seeds / serialisation:** READY (after fix). All
  indexes created idempotently in `ensure_indexes()` at startup. **P0
  blocker found and fixed:** `run_seeds()` used to unconditionally
  create hardcoded-password admin/support/user/fixture accounts and 15
  SampleCo demo jobs → now gated behind `settings.PROD_MODE=false` per
  the seed-guard fix (see CHANGELOG 2026-02-21).
- **Production fail-fast:** READY. Verified via subprocess:
  `PROD_MODE=true + CI_TEST_ISSUER_ENABLED=true` → server refuses to
  boot; `PROD_MODE=true + empty CORS_ALLOW_ORIGINS` → server refuses to
  boot. Confirmed **without** flipping the preview flag.
- **`/api/health`:** READY. Returns 200 with `{ok, mongo, phase,
  policy_text_version}` and does **not** disclose `prod_mode` /
  `ci_test_issuer_enabled` (those live on `/api/v1/admin/health`).
- **Frontend production build:** READY. `yarn build` succeeded in 12s
  → `167.8 kB` gzipped main bundle + `7.07 kB` gzipped CSS. Only
  eslint warnings (unused imports) — no build errors.
- **Backend regression:** READY. Full `pytest tests/` = **356/356 green**
  (was 352 + 3 new deploy-readiness + 1 previously-count-adjusted).

### Deploy-time config required (operator-side, NOT code)
| Item | Preview value | Prod deploy action |
|---|---|---|
| `PROD_MODE` | `false` | Flip to `true` |
| `CI_TEST_ISSUER_ENABLED` | `true` | Flip to `false` |
| `CORS_ALLOW_ORIGINS` | preview host, localhost:3000 | Set to prod host only |
| `JWT_SECRET` | 64-byte random | Rotate on deploy |
| `INTERNAL_SERVICE_TOKEN` | provisioned | Rotate on deploy |
| `EMERGENT_LLM_KEY` | provisioned | Confirm set (activates persistent object storage) |
| Vendor secrets | absent | Provide only when activating provider |
| Webhook URLs | shown in Admin dashboard per provider | Register with each vendor after deploy |

### Preview-only guards (must be verified after deploy flip)
- Seed guard: after `PROD_MODE=true`, prod boot should log
  `PROD_MODE=true — skipping demo companies, sample jobs, and all
  hardcoded-password fixture accounts. Reference data only.` Verify
  no `admin@opportunityos.dev` etc. exist in the prod `users` collection.
- `/api/internal/fixture/rebase` returns 503 in prod mode.
- Google OAuth click-through must be manually verified by a human with
  a real Google account (`HUMAN_REQUIRED`).

Latest platform checkpoint SHA at time of audit: `6f17592e`
(followed by new auto-commit for the seed-guard fix).

---

## 🚧 Founder integrations mandate — ALL MILESTONES DONE (2026-02-21)

Independent verification checkpoints:
- Milestone A → `/app/test_reports/iteration_12.json`
- Milestones B – H → `/app/test_reports/iteration_13.json`
- Advisory fix (webhook HTTP semantics, 503/400/404, never 500/2xx) → `/app/test_reports/iteration_14.json`
- Milestone I visual polish + advisory-fix hardening → `/app/test_reports/iteration_15.json`
- Code-review remediation (4 fixes) → `/app/test_reports/iteration_16.json`

Full backend regression at close of code-review pass: **352 / 352** pytest green.

**Milestone A · Integrations foundation + Admin dashboard — DONE (2026-02-21)**
- Verified: `/app/test_reports/iteration_12.json`. Full backend regression **190 / 190** green.
- 14 provider adapters registered with truthful `status`:
  CONNECTED (`email_password`), TEST_MODE (`stripe`, `openai`, `anthropic`, `gemini`, `media_storage`),
  CONFIGURATION_REQUIRED (`google_auth`, `resend`, `sendgrid`, `twilio`, `elevenlabs`, `razorpay`, `paypal`, `paystack`).
- Admin-only `/api/v1/admin/integrations` list / detail / test / enable / disable.
  Admin UI `IntegrationsTab` renders every provider grouped by category. CSRF, RBAC and
  audit invariants preserved.
- Never leaks env values or secrets — `describe()` returns env-var *names* only.

**Milestone B · Emergent object storage — DONE (2026-02-21)**
- Verified: full backend regression **217 / 217** pytest green (+4 storage tests).
- Real Emergent object-storage backend behind `services.storage.storage` — used
  automatically when `EMERGENT_LLM_KEY` is present. Local disk retained as a
  labelled fallback (`MEDIA_STORAGE_BACKEND=local`).
- No caller change: `domains/documents/service.py` +
  `domains/applications/service.py` remain untouched.
- Provider `media_storage` upgraded from stub to real health / test-connection
  probes. Honestly reports `TEST_MODE` on the shared Emergent surface;
  `CONFIGURATION_REQUIRED` if the key is unset. Never leaks secrets.

**Milestone C · Email (Resend + SendGrid) — DONE (2026-02-21)**
- Verified: full backend regression **231 / 231** pytest green (+14 email tests).
- Real `send()` and `verify_webhook()` on both adapters; hard-fail without
  vendor secrets (Svix HMAC for Resend, ECDSA P-256 for SendGrid).
- New public route `POST /api/webhook/email/{provider}` with signature-based
  auth, dedup via `webhook_events` unique index, no bypass mode.
- No Emergent email provider — adapters stay `CONFIGURATION_REQUIRED` until
  the operator supplies `RESEND_*` / `SENDGRID_*` env vars.

**Milestone D · Twilio Verify (OTP) — DONE (2026-02-21)**
- Verified: full backend regression **238 / 238** pytest green (+7 twilio tests).
- Real `start_verify()` / `check_verify()` + Twilio HMAC-SHA1 signature helper;
  hard-fail on configuration_required and on missing/bad signature.
- Adapter stays `CONFIGURATION_REQUIRED` until operator supplies
  `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_VERIFY_SERVICE_SID`.

**Milestone E · Google Sign-In (Emergent-managed) — DONE (2026-02-21)**
- Verified: full backend regression **245 / 245** pytest green (+7 Google tests).
- End-to-end backend flow: `/api/v1/auth/google/session` +
  `/api/v1/auth/google/complete`. Consent-first — no user row until consent
  scopes submitted. Existing users linked automatically on email match.
- Frontend "Continue with Google" wired on Login + Signup. New
  `/auth/callback` route processes the Emergent redirect and renders the
  five-scope consent form when a new account is being created.
- Provider adapter reports CONNECTED by default (Emergent-managed → no per-
  app client secret). `GOOGLE_AUTH_ENABLED=false` flips to
  CONFIGURATION_REQUIRED as an operator kill-switch.

**Milestone F · Payments strangler + regional adapters — DONE (2026-02-21)**
- Verified: full backend regression **261 / 261** pytest green (+16 payments tests).
- Real cryptographic webhook signature verification for Stripe (HMAC-SHA256),
  Razorpay (HMAC-SHA256), Paystack (HMAC-SHA512). PayPal uses server-to-server
  verification via `/v1/notifications/verify-webhook-signature`.
- Real `create_order()` / `create_checkout_session()` /
  `initialize_transaction()` code paths on all four adapters; hard-fail on
  missing credentials, no bypass mode.
- Legacy `domains/billing/service.py` untouched — strangler-ready for future
  swap-in of the Stripe adapter's `create_checkout_session` / `verify_webhook`.

**Milestone G · AI gateway strangler — DONE (2026-02-21)**
- Verified: full backend regression **266 / 266** pytest green (+5 gateway tests).
- New `services/ai_gateway.py` unified `chat()` router with cost recording on
  both success and failure paths. Selects OpenAI/Anthropic/Gemini adapters via
  the provider registry.
- All three AI adapters now share a single `emergent_chat_singleturn()`
  boundary — one and only one place talks to `emergentintegrations.llm.chat`.
- Existing `services/llm.py` untouched; strangler-ready for a follow-up patch
  that swaps its `_call_model` / `_call_claude` calls to `ai_gateway.chat()`.

**Milestone H · Payment webhooks + ElevenLabs + admin polish — DONE (2026-02-21)**
- Verified: full backend regression **275 / 275** pytest green (+9 Milestone H tests).
- Unified `POST /api/webhook/payment/{slug}` route for stripe / razorpay /
  paystack / paypal with cryptographic verification (or PayPal server-to-server
  round-trip). Hard-fail on missing secret (500), invalid signature (400),
  unknown provider (404). Dedup via `webhook_events` unique index.
- ElevenLabs adapter promoted to real code path — `text_to_speech()`,
  `test_connection()`. Hard-fail without credentials.
- Admin integration detail now surfaces external `webhook_url` for
  payment/email providers so ops can register with vendors without guessing.

**All eight founder integration milestones (A → H) + advisory fix + Milestone I
visual polish DONE.**

Standing item, credential-blocked, awaiting founder-supplied keys:
- Operator-guided credential rollout for CONFIGURATION_REQUIRED providers
  (Resend / SendGrid / Twilio / Razorpay / PayPal / Paystack / ElevenLabs).
  Each provider already exposes truthful missing_env + webhook_url in the
  admin dashboard — supply the keys via `/app/backend/.env` and the
  provider flips to TEST_MODE / CONNECTED without any code change.

Standing requirements per checkpoint:
- Existing regressions must stay green.
- `PRD.md` + `CHANGELOG.md` updated per milestone.
- Report exact tests run, changed files, and blockers.

---

## ✅ v0.1 CERTIFIED — 2026-02-20

**Final commit (pre-security-invariants):** `f51ce95b`
**Final commit (with security-invariants module):** captured as the next auto-commit on top of this write.
**Acceptance Run A–I:** 100 % PASS (see `/app/test_reports/p6-acceptance-run.md`).
**Backend pytest sweep:** **173 / 173** green — 119 phases-1-through-5 + 34 phase-6 acceptance + 2 close-out fix + 18 security invariants.
**Test reports:** `iteration_5..9.json`, junit `pytest/phase6_iter{8,9}.xml`, sanitized user-detail body `p9-admin-user-detail-body.json`.

### Deviations of record (frozen at v0.1)
1. **Auth**: internal JWT+bcrypt with Phase-6 httpOnly-cookie transport migration. Spec originally called for Clerk. Isolated in `domains/auth/*` and `core/{sessions,security,deps}.py` — swappable.
2. **Storage**: `LocalDiskStorage` under `/app/backend/storage`. `documents` rows still carry `s3_key + sha256` for a mechanical S3/Postgres migration later.
3. **Database**: MongoDB with compensating requirements (unique indexes proven by pytest on `canonical_key`, `submission_receipts`, `usage_meters`, partial-open-application, `sessions.session_id`). Spec originally called for Postgres.
4. **CI Bearer path**: `CI_TEST_ISSUER_ENABLED=true` in the preview `.env` so pytest can keep using `Authorization: Bearer …`. Production `.env` MUST set this to `false` and `PROD_MODE=true`; server refuses to start if both are true.
5. **Sealed masking literal**: `"•••• (sealed)"` (matches PRD §Sealed fields below). No unmask capability exists in v0.1 by design.

### Stub inventory pointer
- **Stripe** — TEST-mode via `emergentintegrations`; `/api/webhook/stripe` verification is a labeled stub. Activation: swap `STRIPE_API_KEY` to a live key + wire real signature verification.
- **Inbound response webhook** — `/api/internal/inbound/response` (X-Service-Token gated). Activation: rotate the internal token + wire a real inbound parser.
- **Observability** — `/api/v1/admin/observability/{events,errors}` endpoints return payloads tagged `label: "INTERNAL STUB — Sentry/PostHog equivalent"`. Activation: replace stub writes with SDK calls.
- **Anti-virus scan on uploads** — `av_status="skipped_v0.1"` on every uploaded document. Activation: wire a real AV pipeline pre-parse.

### What must NOT change without a new brief
- Product laws in §Product law
- Sealed-field masking (no unmask path — spec-frozen at v0.1)
- Immutable receipts (append-only, no update / delete surface)
- Consent ledger append-only rule
- Fixture geometry (9 passing / 6 excluded on fixture-ead@ with the seeded 15 SampleCo jobs)

**No further product changes without a new brief.**

---

## Product law
- Candidate-fiduciary. Consent-first. Every state-changing action is authenticated, idempotent, audited.
- Optimize for **qualified interviews**, never application volume.
- The **Career Passport** (approved claims) is the ONLY factual source of truth. No shadow inference gets written back to it.
- No scraping. No password harvesting. No invented facts. No auto-submit without approval.
- Feature allowlist: zip code / age proxies FORBIDDEN in gates or scoring.


## Roles
`user` (default), `support`, `admin`. Admin/support gated via `admin_users` collection.

## Consent scopes (v1.0)
1. `process_career_data` — required to create an account.
2. `discover_jobs` — optional. Guards feed, coverage-preview, link-import.
3. `generate_materials` — optional. Guards Phase 4 tailoring.
4. `track_applications` — optional. Reserved for Phase 5 tracker outbound signals.
5. `email_me` — optional.

Consent ledger is APPEND-ONLY. Revocation = new row with `granted=false`. No delete/update endpoints, ever.

## Idempotency
Every state-changing endpoint (POST/PUT/PATCH/DELETE under `/api/v1/*`) accepts `Idempotency-Key`. Middleware replays the byte-identical body per (user, method, path, key) — no duplicate side effects, no duplicate audit rows.

## Sealed fields
Claims with `sensitivity="sealed"` serialize as `"•••• (sealed)"` for anyone who is not the owning user — including admin and support. The eligibility_profile (when `sensitivity="sealed"`) applies the same mask to its data fields (`status`, `dates`, `notes`, `derived_flags`). No unmask capability exists in v0.1 — future JIT-elevation designs must be a NEW route, not a mutation of `get_user_detail`.

Security invariants: pytest module `tests/test_security_invariants.py` (27 tests) enumerates every admin/user response endpoint and asserts no `password_hash` / `password` / `totp_secret` / `recovery_codes` / `csrf_token` / `session_id` / bcrypt-hash marker (`$2[aby]$`) appears anywhere in the response body. Additionally locks in the post-audit fixes: `/privacy/export` scrub, sibling-session revocation on password change, per-user idempotency scoping under the cookie path, deploy-flag disclosure behaviour, login-brute-force throttle. Adding a new admin GET or a new credential column requires updating that module.

## Phase roadmap
- **Phase 1 (shipped):** Foundation — auth, consent ledger, audit, idempotency, sealed serializer, seeds, gated admin route.
- **Phase 2 (shipped):** Career Passport ingestion & approval flow — resume upload, real LLM parse (gpt-5, fallback gpt-4o), claim lifecycle (approve/reject/edit with `superseded_by`), preferences, eligibility (sealed) + gate engine v0 + coverage preview.
- **Phase 3 (shipped):** 14-gate engine, weighted 0-100 scoring, jobs feed, link import (blocks LinkedIn/Indeed/Handshake), applications tracker with atomic state transitions, usage meters, submission-receipts contract (empty; index proven), LLM cost ledger, golden-set harness.
- **Phase 4 (shipped — 2026-02):** Grounded AI generation (Claude Sonnet 4.5 tailoring + deterministic validator firewall, NO LLM in the reject path), Application Prep flow S10/S11/S12 (validator chip, resume diff with accept/revert + PDF/DOCX export, screeners with sensitive/demographic rules), two-attempt LLM pipeline with template fallback, screener library, ai_generations audit ledger. 104/104 pytest green + full frontend flow verified.
- **Phase 5 (shipped — 2026-02):** Approval + authorization (S13, `authorization_scopes` with 72h TTL, batch approve, revoke), route drawer + guided-manual submit + attest (S14/S15) writing IMMUTABLE `submission_receipts` (unique index on user_id+company_id+req_ref; no update/delete surface anywhere), duplicate guard with NO self-serve override, materials-hash lock (sha256 of accepted-lines+approved-answers; edits after approve → 409 materials_changed), daily-submit-cap enforcement (free 3 / plus 15 / pro 25 / max 40; fixture-ead seeded to plus), tracker kanban Prepared→Submitted→Response→Interview→Offer→Closed (S16) with append-only outcomes, illegal-transition-still-persists-outcome contract, QI confirm flow, labeled inbound-parse forward-address stub + `/api/internal/inbound/response` webhook (X-Service-Token gate + idempotent by ext_message_id), personal analytics funnel (S17) with SAMPLE bucket separated + no cohort stats + honest empty states. 117/117 pytest green + full frontend flow verified via testing agent.
- **Phase 6 (shipped — 2026-02):** Stripe test-mode billing (checkout / cancel / refund / invoices + FOUNDER19 coupon), plan-cap gates (jobs_processed hourly, applications_prepared monthly, apps_submitted daily), privacy (consents view/revoke, release log, JSON data export, 30-day soft-delete + startup sweep), admin console (users search + masked detail with audit-on-view, refunds with reason enum, manual-queue resolve, feature-flags CRUD, support tickets, system health, observability stubs), support role = READ-ONLY except support tickets (server-side enforced), **auth hardening** — httpOnly `oppos_session` cookie (SameSite=Lax for user, SameSite=Strict for admin/support) + JS-readable `oppos_csrf` cookie + CSRF double-submit middleware, server-side session store in `sessions` collection (revocation-capable, TTL-swept), CORS explicit origin allowlist with credentials, CI-only Bearer issuer flag `CI_TEST_ISSUER_ENABLED` with PROD_MODE fail-fast, startup guard for duplicate FastAPI operation_ids. Stub `domains/admin/router.py` + `domains/admin/models.py` deleted.

## Integrations
- **LLM:** `EMERGENT_LLM_KEY` via `emergentintegrations`. Resume parsing pinned to primary `gpt-5` w/ fallback `gpt-4o`. Actual model string persists on every parsed claim's `source.model` and on `documents.parse_meta.model_used`. Every call appends to `llm_costs` (task, model, tokens_in/out, cost_usd_est, price_source, ts).
- **Storage:** local disk at `/app/backend/storage` behind an S3-compatible interface.
- **Email / analytics / error tracking:** internal stubs.
- **Background queue:** `services/queue_stub.py` (asyncio semaphore).
- **Anti-virus:** `av_status="skipped_v0.1"` on every uploaded document.
- **Billing:** deferred to Phase 6.
- **Internal ingest:** `POST /api/internal/jobs/bulk` guarded by `INTERNAL_SERVICE_TOKEN` header (missing→401, wrong→403, not-configured→503; token never appears in logs/bodies).

## Deviations of record
- Auth: internal JWT+bcrypt (docs originally specified Clerk). Isolated in `domains/auth/*` — swappable. **Phase 6 update:** transport migrated to server-side sessions in Mongo (`sessions` collection) with httpOnly `oppos_session` cookie (SameSite=Lax user, Strict admin/support) + JS-readable `oppos_csrf` cookie enforcing double-submit on every POST/PUT/PATCH/DELETE under `/api/v1/*`. Bearer JWT survives ONLY when `CI_TEST_ISSUER_ENABLED=true` (pytest / internal probes), server refuses to start if that flag is on in `PROD_MODE=true`. Internal `/api/internal/*` routes remain gated by `X-Service-Token` unchanged.
- Storage: `LocalDiskStorage` under `/app/backend/storage`. `documents` rows still carry `s3_key + sha256` for a mechanical Postgres/S3 migration later.
- Mongo (spec called for Postgres): **compensating requirements** implemented — unique indexes proven by pytest (canonical_key, submission_receipts, usage_meters, partial-open-application), atomic state transitions via `find_one_and_update` with expected-state precondition, field names verbatim from spec.

## Phase 3 endpoints delivered
- `GET  /api/v1/jobs/feed` — passing + excluded jobs, weights_version, gate results, route decision
- `GET  /api/v1/jobs/{id}` — job detail w/ have/gap, gates, reason codes, route
- `POST /api/v1/jobs/import` — user link import (409 for LinkedIn / Indeed / Handshake)
- `GET  /api/v1/jobs/imports/me`
- `POST /api/v1/jobs/{id}/resolve` — resolve a derived import to the employer origin
- `POST /api/v1/jobs/{id}/hide`
- `POST /api/v1/jobs/{id}/shortlist` — creates an application row (409 on duplicate open)
- `POST /api/internal/jobs/bulk` — internal ingest (X-Service-Token)
- `GET  /api/v1/applications` — user's tracked applications
- `PATCH /api/v1/applications/{id}/state` — atomic transition (expected_state precondition)
- `GET  /api/v1/matches/for-job/{id}` — full weighted breakdown w/ weights_version
- `POST /api/v1/matches/for-job/{id}/feedback` — helpful / not helpful
- `GET  /api/v1/usage/me` — per-period usage meter

## Phase 3 gate contract (14 gates, exact names)
`vacancy_open`, `authorization_scope`, `duplicate_check`, `work_auth`, `sponsorship`,
`stem_opt_viability`, `itar`, `security_clearance`, `licensure`, `location_onsite`,
`experience_band`, `education_requirement`, `salary_floor`, `employer_exclusions`.

`authorization_scope` is interface-only in Phase 3 (always `pass`); enforcement lands with the
Phase 5 submit path.

## Phase 3 scoring contract (WEIGHTS_VERSION = "v0.1", sum = 100)
role_fit 25, skills_coverage 20, experience_band_fit 10, eligibility_margin 10,
location_comp_fit 10, freshness 8, competition_estimate 7, employer_responsiveness_prior 5,
preference_affinity 5.

UNKNOWN factors are renormalized out honestly (weight not counted, confidence = used_weight/100).
A gate FAIL caps score at 25.

## Frontend surfaces (Phase 3)
- `/feed` (S7) — passing cards w/ score badge, gate/route/freshness chips, "Why this score?" opens S9 modal.
- Excluded intelligence layer w/ reason chips on every excluded card. SAMPLE rows badged; passing-count excludes SAMPLE.
- Link-import box (S7): 409 route_unavailable_platform_policy w/ plain-language explanation and finder helper.
- `/jobs/:id` (S8) — full JD, gate verdict list (all 14), have/gap on approved claims only, route decision, resolve-origin form for derived imports.
- Match explain modal (S9) — weights_version + confidence + per-factor bars w/ UNKNOWN rendered as gray, no interview-probability anywhere. Feedback POST /matches/…/feedback.
- `/applications` — real state tracker w/ atomic transition menu; SAMPLE rows shown but excluded from metric counts.
- Passport UI now includes `DocumentHistory` panel (Phase 2 polish carryover).
- Topbar `UsageMeterChip` shows current month `jobs_processed` count.

## Testing
- `pytest tests/` — 79 tests green (autouse module-scope rebase in `tests/conftest.py`
  keeps state deterministic across runs).
- Golden set: `python3 -m tests.golden_resumes.golden_run` — 10 labeled synthetic
  résumés; target ≥95% field accuracy; last report at
  `tests/golden_resumes/last_report.json`. Current: 98.95%.

## Phase 4 endpoints delivered
- `POST /api/v1/applications/{id}/prepare` — consent-gated (`generate_materials`); transitions shortlisted→preparing, runs the two-attempt grounded LLM pipeline (Claude Sonnet 4.5) + validator, falls back to a deterministic template if both attempts fail validation, persists a tailored `resume_version` with `render_manifest.lines[]` (each line carries claim_ids), `validator_result`, `outcome`.
- `POST /api/v1/applications/{id}/regenerate` — same pipeline with an optional user instruction; `refuse_instruction` catches PMP/Stanford/patent bait-instructions BEFORE the LLM sees them and returns `{refusal: {reason: missing_claim:*, message}}` in the response.
- `POST /api/v1/applications/{id}/resume-lines/{lineId}` — accept/revert an individual line, status persists on the resume_version.
- `POST /api/v1/applications/{id}/ready-for-approval` — atomic preparing→awaiting_approval transition; gate now inspects the JOB's `screener_questions` and requires an approved answer for each `sensitive_visa` / `sensitive_salary` / `sensitive_clearance` qid (409 with `unmet_question_ids` if any are missing).
- `GET  /api/v1/applications/{id}/prep` — full packet: application + tailored resume + base resume + generation history + screeners.
- `GET  /api/v1/applications/{id}/export/{pdf|docx}` — renders the accepted (or proposed, on fresh prepare) lines via reportlab / python-docx; provenance stored on `resume_versions.exports.{fmt}`.
- `GET  /api/v1/applications/{id}/screeners` — merges job questions with any user answers; adds `sensitive`/`static_only` flags for UI routing.
- `POST /api/v1/applications/{id}/screeners/{qid}/answer` — 400 on `kind=demographic` (never stored). Sensitive kinds require explicit `approved=true` per application.
- `POST /api/v1/applications/{id}/screeners/{qid}/generate` — 400 on sensitive_* or demographic kinds. Otherwise: grounded generation using the same claim-referencing pipeline.
- `GET/POST /api/v1/screening-answers/library` — reusable user-owned library of answers.

## Phase 4 grounding rules (enforced by `services/validator.py`)
- R4 grounding law: every AI-generated line MUST reference at least one APPROVED claim id; validator is deterministic (no LLM in the reject path). Rejection reasons: `empty_claim_ids`, `unapproved_claim:<id>`, `number_not_in_claims:<n>`, `date_not_in_claims:<yyyy>`, `sensitive_leak:<claim_type>`, `malformed_line`.
- R5 sensitive-leak scan: sealed claim value leaf tokens (>=3 chars) may NEVER surface in text without an explicit per-application approval for that scope.
- R5 refusal law: instruction phrases like "Add my PMP certification" / "include my Stanford PhD" / "mention my patent" are refused BEFORE the LLM is called if no approved claim's flattened text names that entity.

## Phase 4 frontend surfaces
- `/applications/:applicationId/prep` (S10/S11/S12) — 3-tab UI with a validator-status chip in the header (green when passed, amber for template fallback, red on refusal). Resume tab shows base vs tailored side-by-side, accept/revert per line, PDF+DOCX export, grounded regenerate with refusal banner. Screeners tab renders `sensitive_*` questions in AMBER with typed/library input + per-application approval checkbox and NO generate button; demographic questions render as static text with zero editable descendants. Summary tab surfaces the sensitive-open counter and disables Ready-for-approval until it reads 0.


## Fixture rebase on demand
`POST /api/internal/fixture/rebase` — same `X-Service-Token` semantics as
`/api/internal/jobs/bulk` (missing→401, wrong→403, not-configured→503, token never
logged/returned). Fully re-baselines fixture-ead@ (wipes applications, hidden_jobs,
match_scores, usage_meters, score_feedback, documents, resume_versions, claims,
consent_records + any jobs the fixture imported + any test-ingest job pollution)
and re-seeds passport-activated + all consents + eligibility=ead_opt sealed + prefs
Phoenix+Remote+$90k + approved claims. Call this BEFORE each acceptance run in CI.

## Deterministic test fixture
- Fixture user `fixture-ead@opportunityos.dev` / `Fixture!Test1` is RE-BASELINED on
  every backend startup — applications/hidden_jobs/match_scores/usage_meters/documents/
  resume_versions/score_feedback/claims/consent_records are wiped, then re-seeded to
  the acceptance-check-B state (passport activated, all consents granted,
  eligibility=ead_opt sealed, prefs Phoenix+Remote+$90k floor, claims incl. MS +
  employment 2020-08→present + skills MATLAB/Simulink/SolidWorks).
- Against the reshaped 15 SampleCo seeds this fixture yields exactly:
  `feed.totals = {passing: 9, excluded: 6}`, fail_reasons
  `{no_sponsorship_offered: 4, requires_us_person: 2}`. Coverage-preview identical.
- **User Zero (`ujjwal@`) is a real seeded candidate and is NOT re-baselined.**
  A one-time marker (`seed_migrations.key=user_zero_cleanup_v3`) applied a single
  cleanup to remove tester pollution accumulated in earlier iterations. Claims +
  consent_records + audit_logs are preserved (append-only rule).
- **All future automated tests use the fixture user.**

## Phase 5 endpoints delivered
- `POST /api/v1/applications/{id}/approve` — computes materials_hash + creates 72h `authorization_scopes` row; awaiting_approval → approved
- `POST /api/v1/applications/approve-batch` — batch approve with per-row failure reporting
- `POST /api/v1/applications/{id}/revoke-authorization` — revokes latest auth; approved → awaiting_approval
- `POST /api/v1/applications/{id}/submit` — approved → submitting; enforces auth (present/unexpired/unrevoked/hash-match) + daily cap + duplicate; returns packet (origin URL, accepted lines, approved answers, route, materials hash)
- `POST /api/v1/applications/{id}/attest` — submitting → submitted; writes IMMUTABLE receipt (409 duplicate_receipt on collision); bumps usage_meters.apps_submitted (idempotent); consent-gated on track_applications
- `GET  /api/v1/applications/{id}/receipt` — retrieves the effective receipt for an app
- `GET  /api/v1/applications/receipts/mine` — list current user's receipts (newest first)
- `GET  /api/v1/applications/duplicate-check?company_id&req_ref` — prior-receipt lookup used by UI + submit gate
- `GET  /api/v1/subscriptions/me` — plan + daily_submit_cap (auto-provisions free plan)
- `GET  /api/v1/tracker` — kanban columns (consent-gated on track_applications)
- `POST /api/v1/applications/{id}/outcomes` — append-only outcome + atomic state transition; illegal transitions 409 but keep the outcome row
- `GET  /api/v1/applications/{id}/outcomes` — full ledger for an app
- `POST /api/v1/applications/{id}/interviews` — schedule; `POST /api/v1/interviews/{id}/qualified` — QI confirm
- `GET  /api/v1/tracker/forward-address` — labeled inbound-parse stub address
- `POST /api/internal/inbound/response` — X-Service-Token webhook; idempotent by (user_id, ext_message_id); appends outcome with source=parsed
- `GET  /api/v1/analytics/funnel` — personal funnel + QI counter + minutes_to_prepare + SAMPLE bucket separation

## Phase 5 collections + indexes
- `subscriptions` — unique on user_id; plan enum free|plus|pro|max
- `authorization_scopes` — (user_id, kind, target) index + (user_id, target, created_at DESC) latest-lookup index
- `outcomes` — (user_id, application_id, ts DESC); unique partial index on (user_id, ext_message_id) for webhook idempotency
- `interviews` — (user_id, application_id)
- `manual_queue_items` — unique on application_id
- `submission_receipts` — unique on (user_id, company_id, req_ref); by-user-ts secondary index

