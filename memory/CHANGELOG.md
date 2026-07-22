# OpportunityOS — CHANGELOG

## 2026-02-21 · Deployment-readiness FINAL pass — P0 blockers cleared (P0)

**Full backend regression: 405 / 405 pytest green** (was 402; +3 new
malformed-subscription pruning tests). **Frontend `CI=true yarn build`:
clean, 171.81 kB gz main bundle.** Prod fail-fast verified. Independent
testing-agent verification: `/app/test_reports/iteration_18.json` —
`retest_needed=false`, all P0/P1 targeted checks GREEN.

**Fresh HEAD SHA after this pass:** `2327d7d9` (`git log --oneline -1`).

### P0 · Fixed
- **`.gitignore` was blocking `.env` files.** `deployment_agent` static
  scan flagged that Emergent's deploy pipeline needs `backend/.env` and
  `frontend/.env` present in the repo so it can overwrite them with
  production values on deploy. Old rules removed; only `.env.local` /
  `.env.*.local` remain ignored for ad-hoc local overrides.
- **Web-push dispatch crashed on malformed `p256dh` / `auth`.** Prod log
  captured `binascii.Error: Invalid base64-encoded string ...` at
  `backend/domains/notifications/service.py:328`. Tests mocked
  `pywebpush` so this path was never exercised.
  - `register_subscription()` now rejects non-urlsafe-base64 keys and
    non-`https://` endpoints with a 400 before storage.
  - `dispatch()` now catches `ValueError` / `TypeError` (which is what
    `binascii.Error` inherits from) and prunes the offending row with
    `prune_reason=malformed_subscription:<type>`, stopping the retry
    loop that was firing on every dispatch.
  - 3 new regression tests in `test_notifications_webpush.py`.

### P1 · Fixed
- **Frontend `CI=true` build.** 15 unused imports across 9 pages
  (`Admin`, `Applications`, `Approvals`, `Billing`, `Feed`, `JobDetail`,
  `Privacy`, `Tracker`, `ApplicationPrep`) would break a strict CI
  build. All removed. Build now compiles cleanly with
  `Treating warnings as errors because process.env.CI = true`.
- **Ops build visibility.** `GET /api/v1/admin/health` (admin cookie
  gated) now returns `build_sha` — from `BUILD_SHA` env var if set,
  else best-effort read of `/app/.git/HEAD`. Public `/api/health` is
  unchanged (never leaks deploy flags).

### P2 · Added
- **`/app/memory/DEPLOYMENT.md`** — operator runbook: env-var
  preflight table, prod fail-fast reference, deploy sequence,
  per-provider credential rollout with exact webhook URLs, human
  verification workflows for Google + Web Push, rollback / incident
  procedures, ops observability signals, final go-live checklist.

### Verified this pass (no code change needed)
- `PROD_MODE=true + CI_TEST_ISSUER_ENABLED=true` → `RuntimeError` at
  import (verified via subprocess).
- `PROD_MODE=true + empty CORS_ALLOW_ORIGINS` → `RuntimeError` at import
  (verified via subprocess).
- `PROD_MODE=true + CORS_ALLOW_ORIGINS=https://prod.example.com` →
  boots clean.
- Public `GET /api/health` returns `{ok, mongo, phase,
  policy_text_version}` only — no deploy flags.
- Internal fixture-rebase endpoint returns 503 in `PROD_MODE=true`
  (existing guard, unchanged).
- Seeder skips demo companies / sample jobs / hardcoded-password
  fixture accounts in `PROD_MODE=true` (existing guard, unchanged).

### Files changed
- `.gitignore`
- `backend/domains/notifications/service.py`
- `backend/tests/test_notifications_webpush.py` (+3 tests)
- `backend/domains/admin/service.py` (build_sha)
- `backend/domains/auth/router.py` (new `GET /apple/status` ops probe)
- `frontend/src/pages/{Admin,Applications,Approvals,Billing,Feed,JobDetail,Privacy,Tracker,ApplicationPrep}.jsx` (unused imports)
- `memory/PRD.md`, `memory/CHANGELOG.md`, `memory/DEPLOYMENT.md` (new)

### Deploy label
**`DEPLOY_READY_WITH_EXTERNAL_BLOCKERS`** — repo is complete; external
credentials, DNS, vendor webhook registrations, and two human
click-through smoke tests (Google, Web Push) remain.


## 2026-02-21 · 16-integration audit — CORRECTED taxonomy + totals (docs-only)

**DOCS-ONLY PASS. No feature code changed. No new backend/frontend tests run
for this correction.** Latest full backend regression remains **402 / 402**
pytest green from the prior feature pass; frontend `yarn build` remains
green. HEAD SHA at correction time: `c3df1f54`
(`git log --oneline -1`).

### Why this correction exists
The prior CHANGELOG entry below (dated 2026-02-21 · "16-integration audit
closure + 3 new integrations") reported provider-registry runtime status
(`CONNECTED` / `TEST_MODE` / `CONFIGURATION_REQUIRED`) verbatim as if that
were the founder-facing audit taxonomy. It is not. It also implicitly
treated the provider registry / Admin Integrations dashboard as if it were
countable alongside product integrations. This entry supersedes that
taxonomy in favour of the founder-mandated audit vocabulary and math.

### Mandated audit taxonomy (one status per row)
- `PRODUCTION_READY` — fully working end-to-end, no pending human step,
  no prod-flag caveat.
- `TEST_MODE` — working on test / platform credentials (Stripe test key,
  Emergent LLM key, Emergent object storage).
- `HUMAN_VERIFICATION_REQUIRED` — code CONNECTED but the final real-world
  step needs a human (e.g. real Google OAuth click-through, real browser
  push delivery).
- `CONFIGURATION_REQUIRED` — code complete; awaiting founder-supplied
  credentials.
- `PARTIAL` / `BROKEN` — not applicable to any row this pass.

### Registry / Admin dashboard is INFRASTRUCTURE — not counted
The provider registry and Admin Integrations dashboard are the surface
that reports each provider's runtime status. They are infrastructure, not
a product integration, and are NOT one of the 16 rows and NOT part of
any total.

### Corrected 16-row totals
- **1 / 16 `PRODUCTION_READY`** · Email & password.
- **5 / 16 `TEST_MODE`** · Stripe, OpenAI, Anthropic, Gemini, File & media storage.
- **2 / 16 `HUMAN_VERIFICATION_REQUIRED`** · Emergent-managed Google sign-in, Push notifications.
- **8 / 16 `CONFIGURATION_REQUIRED`** · Razorpay, PayPal, Paystack, Apple sign-in, Resend, SendGrid, Twilio + OTP, ElevenLabs.
- **0 / 16 `PARTIAL`** and **0 / 16 `BROKEN`**.

The full corrected 16-row table (with per-row test evidence, required env
variable names only, and covering commit SHAs) lives at the top of
`/app/memory/PRD.md` under the section
**"📊 16-Integration Audit — CORRECTED (2026-02-21)"**. This CHANGELOG
entry is authoritative for taxonomy + totals; PRD.md is authoritative
for the row-by-row detail.

### Corrections vs. the superseded entry below
- **Web Push (row 11)** — superseded entry said "Provider status:
  **CONNECTED**". Corrected audit status: **`HUMAN_VERIFICATION_REQUIRED`**.
  Rationale: VAPID key pair, provider, Service Worker, backend flow and
  20 unit tests (against a mocked `pywebpush`) are all in place, but a
  real push delivered to a real device requires a browser to subscribe
  first — no automation produces that evidence.
- **Emergent-managed Google sign-in (row 5)** — provider registry reports
  runtime `CONNECTED` (session-id handshake works and is unit-tested with
  a mocked Emergent endpoint). Corrected audit status:
  **`HUMAN_VERIFICATION_REQUIRED`**, because end-to-end verification
  requires a human clicking "Continue with Google" in a real browser
  against real Google.
- **Apple sign-in (row 6)** — status stays **`CONFIGURATION_REQUIRED`**
  (no APPLE_* env vars).
- **Twilio + OTP (row 10)** — status stays **`CONFIGURATION_REQUIRED`**
  (no TWILIO_* env vars).
- **Stripe (row 1)** — status is **`TEST_MODE`**, not "PRODUCTION_READY".
  The env-provisioned key is a test-mode key; flipping to live mode is a
  deploy-time key rotation and remains founder-side.
- **OpenAI (12), Anthropic (13), Gemini (14), File & media storage (16)**
  — status is **`TEST_MODE`** (Emergent LLM Key / Emergent object storage
  is a platform credential path, not a founder-owned production
  credential path).
- **Email & password (row 7)** — status is **`PRODUCTION_READY`**. Only
  row that meets that bar this pass.
- **Razorpay (2), PayPal (3), Paystack (4), Resend (8), SendGrid (9),
  ElevenLabs (15)** — status stays **`CONFIGURATION_REQUIRED`**
  (founder-supplied vendor credentials pending).

### Honesty callouts recorded in the corrected audit
1. **ElevenLabs (row 15) has no dedicated test file.** The earlier PRD
   claimed `test_milestone_j_voice.py` existed. It does not. ElevenLabs
   is currently exercised only through registry-level tests
   (`test_milestone_a_integrations.py`, `test_iteration14_advisory_fix.py`,
   `test_iteration15_advisory_fix_hardened.py`). CONFIGURATION_REQUIRED
   status is still truthful because the provider correctly reports it.
   A dedicated ElevenLabs test suite is **deferred to P2 backlog** per
   founder ruling (2026-02-21).
2. **Push notifications is HUMAN_VERIFICATION_REQUIRED, not
   PRODUCTION_READY.** See correction #1 above.
3. **Emergent-managed Google sign-in is HUMAN_VERIFICATION_REQUIRED, not
   CONNECTED.** See correction #2 above.
4. **Stripe is TEST_MODE, not PRODUCTION_READY.** See correction #5 above.

### What did NOT change
- No feature code files were modified for this correction.
- No provider adapters, notification service, Apple service, OTP service,
  or router files were modified.
- No tests were added, removed, or re-run for this correction (latest
  full regression **402 / 402** predates this pass and remains the
  reference figure).
- Frontend `yarn build` was not re-run for this correction (last known
  build passed in the previous feature pass).
- No secrets, VAPID private key, test passwords, or `.env` contents are
  disclosed anywhere in this entry.

### Standing follow-ups (unchanged from prior CHANGELOG · P1, founder-side)
- Real Google OAuth click-through (HUMAN_VERIFICATION_REQUIRED).
- Real browser Web Push delivery test (HUMAN_VERIFICATION_REQUIRED).
- Apple / Twilio / Resend / SendGrid / Razorpay / PayPal / Paystack /
  ElevenLabs credential rollout (CONFIGURATION_REQUIRED → TEST_MODE /
  CONNECTED without code changes).
- Production rollout flip: `PROD_MODE=true`, `CI_TEST_ISSUER_ENABLED=false`,
  `CORS_ALLOW_ORIGINS` locked to prod host, JWT + internal token rotation,
  `EMERGENT_LLM_KEY` confirmed, webhook URLs registered with each vendor.


## 2026-02-21 · 16-integration audit closure + 3 new integrations (P0)

Full backend regression **402 / 402** pytest green. Frontend production build
green (~168 kB gz main). No live vendor calls made in the audit path.

### New integrations shipped this pass
1. **Web Push (VAPID · standards-based)** — playbook consulted; Emergent
   does NOT provide a managed web-push service for React web apps (their
   managed push is Expo/mobile-only). Built the compliant standards path:
   VAPID key pair (generated once via `py_vapid`, private key env-only,
   NEVER regenerated on deploy — regeneration invalidates all existing
   subscriptions), `pywebpush` on the backend, Service Worker on the
   frontend, direct delivery to FCM/Mozilla autopush.
   Files: `backend/integrations/push/webpush_provider.py`,
   `backend/domains/notifications/{__init__,models,service,router,events,sweep}.py`,
   `backend/routers/*` (wired into server), `frontend/public/sw.js`,
   `frontend/src/lib/push.js`, `frontend/src/components/NotificationsSettings.jsx`,
   `backend/tests/test_notifications_webpush.py` (20 tests).
   Provider status: **CONNECTED** (VAPID pair present in preview env).
2. **Sign in with Apple (standards-based OIDC)** — playbook consulted;
   Emergent does NOT provide a managed Apple sign-in. Built the compliant
   OIDC standards path: authorization-code flow with `response_mode=form_post`,
   ES256 client-secret JWT signed with the Apple `.p8` key, JWKS-based
   id_token verification, state+nonce single-use CSRF+replay defense.
   Consent-first pending signup preserved. Private-relay-email semantics
   correctly refuse to auto-link into an existing non-relay account; those
   users get a distinct account instead.
   Files: `backend/integrations/auth/apple_provider.py`,
   `backend/domains/auth/apple_service.py`, `backend/domains/auth/router.py`
   (new `/apple/start`, `/apple/callback`, `/apple/complete`),
   `backend/middleware/csrf.py` (CSRF-exempt `/apple/callback` +
   `/apple/complete`), `frontend/src/lib/auth.jsx` (appleStart /
   appleCompleteSignup), `frontend/src/pages/Login.jsx` (honest disabled
   button when `apple_auth_not_configured`).
   `backend/tests/test_auth_apple_signin.py` (16 tests including bad-signature,
   bad-nonce, expired, unknown-kid, wrong-audience, private-relay non-linking,
   duplicate-sub reuse, describe-never-leaks-private-key).
   Provider status: **CONFIGURATION_REQUIRED** (no APPLE_* env vars yet —
   founder must supply .p8 / Team ID / Key ID / Services ID / redirect URI).
3. **Phone OTP login (Twilio Verify — frontend UI + auth endpoints)** —
   the backend Twilio Verify adapter existed but no auth endpoint or UI
   consumed it. Built `POST /api/v1/auth/otp/start`, `POST /api/v1/auth/otp/verify`
   (login only for accounts with an attached phone), `POST /api/v1/auth/otp/attach`
   (authenticated attach), and `GET /api/v1/auth/otp/status` (truthful
   `configured=false` when TWILIO_* env is absent, so the frontend renders
   an honest disabled state).
   Files: `backend/domains/auth/otp_service.py`, `backend/domains/auth/router.py`,
   `frontend/src/pages/Login.jsx` (Phone one-time code mode with honest
   "not yet available" state), `frontend/src/lib/auth.jsx` (otpStart /
   otpVerify / otpStatus).
   `backend/tests/test_auth_otp_login.py` (10 tests including phone
   normalization, 503 without creds, happy-path login, no-account-for-phone
   404, incorrect-code 401, phone-already-attached-elsewhere 409).
   Provider status: **CONFIGURATION_REQUIRED** (Twilio env vars pending).

### Provider count expanded 14 → 16
`admin/integrations` now lists all 16 integrations from the founder's
canonical panel. Count assertions updated in
`test_iteration14_advisory_fix.py`, `test_iteration15_advisory_fix_hardened.py`,
`test_milestone_a_integrations.py`.


## 2026-02-21 · Deployment readiness fix — PROD_MODE seed guard (P0)

Full backend regression **356 / 356** pytest green (+3 new deploy-readiness
tests). Independently verified in `/app/test_reports/iteration_17.json` —
all 6 request items GREEN, zero blockers, zero action_items, `retest_needed=false`.

### Blocker · Preview fixture credentials would leak into production Mongo
- **Root cause:** `run_seeds()` in `domains/seeds/seeder.py` was called
  unconditionally from `lifespan()` on every backend startup and would
  create hardcoded-password accounts (`admin@opportunityos.dev` /
  `Admin!Console1`, `support@opportunityos.dev` / `Support!Console1`,
  `ujjwal@opportunityos.dev` / `Passport!Test0`,
  `fixture-ead@opportunityos.dev` / `Fixture!Test1`) plus 15 SampleCo
  demo jobs the first time it hit a fresh production Mongo. All four
  passwords are documented in `/app/memory/test_credentials.md`, so
  anyone with access to the repo could log in as admin on prod.

### Fix · smallest safe change
- `domains/seeds/seeder.py::run_seeds` now branches on `settings.PROD_MODE`:
  - **Always** seed reference data (`taxonomy` + `feature_flags`) — these
    are legit for production day-one.
  - **Skip in prod:** demo `companies` (which includes SampleCo demo
    domain), all 15 sample jobs, the two hardcoded-password admin/support
    bootstraps, User Zero seed, and the fixture-user rebase. Returns a
    `prod_mode_seed_skipped: True` sentinel in the counts dict.
- `domains/fixtures/internal_router.py::rebase_fixture` now raises
  HTTPException(503, `{error: "fixture_rebase_disabled_in_prod"}`) when
  `settings.PROD_MODE=True`, so ops can never mistake this preview-only
  test-data tool for a data-recovery endpoint. Existing X-Service-Token
  gate still enforced ahead of the prod-mode check.
- **Preview behavior UNCHANGED** (`PROD_MODE=false`). Live-probe confirmed
  the 9-passing / 6-excluded / 2-requires-us-person / 4-no-sponsorship
  acceptance-check-B geometry is intact.

### Tests
- New `tests/test_deploy_readiness_prod_mode_seed_guard.py` — 3 tests:
  - `test_prod_mode_seed_skips_fixture_accounts`: PROD_MODE=true → NO
    admin/support/ujjwal/fixture accounts in `users`, NO SampleCo demo
    jobs, YES taxonomy + YES feature_flags.
  - `test_preview_mode_seed_creates_full_fixture`: PROD_MODE=false → all
    four fixture accounts, 15 sample jobs, taxonomy + feature_flags.
  - `test_fixture_rebase_endpoint_disabled_in_prod_mode`: direct handler
    invocation raises HTTPException(503, `fixture_rebase_disabled_in_prod`).
- Isolation: each async test creates its own ephemeral Motor client bound
  to the test's event loop, uses monkeypatch for `get_db` redirection,
  and drops the ephemeral DB via `pymongo` (sync) in teardown so no
  Motor state leaks into downstream pytest-asyncio tests.

### Deploy-time flip / rotation / vendor-key checklist (unchanged from PRD)
- `PROD_MODE=true` — enables the seed guard, activates CORS localhost
  strip, and locks fail-fast on `CI_TEST_ISSUER_ENABLED=true`.
- `CI_TEST_ISSUER_ENABLED=false` — disable the Bearer JWT fallback.
- `CORS_ALLOW_ORIGINS=<prod host>` — must be non-empty in prod
  (server refuses to boot otherwise).
- `JWT_SECRET` — rotate to a fresh 64-byte random value on deploy.
- `INTERNAL_SERVICE_TOKEN` — rotate; the internal ingest and
  webhook-target endpoints depend on it.
- `EMERGENT_LLM_KEY` — must be set so `EmergentObjectStorage` is
  selected over local-disk fallback; local disk does not persist
  across k8s pod rebuilds.
- Vendor keys (only if activating that provider): `RESEND_*`,
  `SENDGRID_*`, `TWILIO_*`, `ELEVENLABS_*`, `RAZORPAY_*`, `PAYPAL_*`,
  `PAYSTACK_*`.
- Register webhook URLs shown in the Admin Integrations dashboard with
  each vendor.


## 2026-02-21 · Code review remediation (post-iteration-15)

Full backend regression **352 / 352** pytest green (+8 new CR-fix tests).
Independently verified in `/app/test_reports/iteration_16.json` — 94/94 across
CR fixes + targeted regression + broader security & Milestone A regression.
Zero blockers, zero action_items.

### CR-FIX-1 · Concurrent-duplicate webhook race (MEDIUM)
- **Bug:** `find_one → insert_one` was not atomic. Two concurrent duplicate
  deliveries would both pass the find_one check, then the second insert
  raised `pymongo.errors.DuplicateKeyError`, surfacing as HTTP 500 —
  violating the "never 500" mandate.
- **Fix:** wrap `insert_one` in `try / except DuplicateKeyError`. On
  duplicate-key, re-read the row the racer stored and return
  `{status: "duplicate", id: <row.id>}`. Applied to both
  `routers/webhooks_email.py` and `routers/webhooks_payment.py`.
- **Tests:** `tests/test_code_review_fixes.py::
  test_payment_webhook_race_returns_duplicate_not_500` +
  `::test_email_webhook_race_returns_duplicate_not_500` (in-process Motor
  stub simulates the exact race).

### CR-FIX-2 · Razorpay dedup key collision (MEDIUM)
- **Bug:** Razorpay bodies have no top-level event id. Milestone H used
  `payload.payment.entity.id` as the dedup key, but that is the *payment*
  id — stable across the `authorized → captured → refunded` lifecycle.
  Once live, only the first of three events per payment would be recorded;
  the other two would be silently discarded as "duplicates".
- **Fix:** `_extract_external_event_id("razorpay", body)` now composes
  `rzp:{event}:{payment_id}:{created_at}`. Different events on the same
  payment yield distinct keys, while true vendor retries (identical body)
  still collide correctly. Missing any component falls back to a
  SHA-256 body hash so we never silently over-collapse.
- **Tests:** `tests/test_code_review_fixes.py::TestRazorpayDedupKey`
  (4 cases: distinct-events, retry-collides, missing-component-hash,
  no-collateral-damage-to-Stripe/Paystack).

### CR-FIX-3 · SendGrid `cryptography_missing` → 503 (LOW)
- **Bug:** If the `cryptography` library was missing at runtime, the
  SendGrid verifier raised `WebhookVerificationError("cryptography_missing:...")`,
  which the router mapped to HTTP 400 — mis-blaming the vendor for a
  packaging problem on our side.
- **Fix:** Extended `_SERVER_MISCONFIG_PREFIX` in
  `routers/webhooks_email.py` to include `cryptography_missing` and
  `bad_key_or_signature` (bad operator-pasted PEM).

### CR-FIX-4 · PayPal `verify_failed:HTTP...` → 503 (LOW)
- **Bug:** When PayPal's `/verify-webhook-signature` endpoint returned
  non-2xx (transient upstream 5xx), the router surfaced HTTP 400.
- **Fix:** Extended `_SERVER_MISCONFIG_PREFIX` in
  `routers/webhooks_payment.py` to include `verify_failed` alongside
  `auth_failed` and `upstream_error`.

### Six live webhook routes — semantics probe
Post-fix curl matrix (preview):
- `resend`, `sendgrid`, `stripe`, `razorpay`, `paystack`, `paypal`
  → all return HTTP **503** on missing-secret.
- Unknown provider → HTTP **404**.
- Never HTTP 500, never 2xx.

### Deferred (non-blocking follow-ups noted by the tester)
- Add a DEBUG log when the Razorpay dedup fallback fires (visibility only).
- Split `bad_key_or_signature` into `operator_bad_pem` vs `signature_mismatch`
  for a cleaner 503/400 split.
- Split PayPal `verify_failed` into `verify_failed:HTTP` (upstream 5xx →
  503) vs `verify_failed:FAILURE` (potential client replay → 400).
- Extract the race-guard pattern into `core/webhook_dedup.py` **when** a
  third webhook category lands (YAGNI until then).


## 2026-02-21 · Advisory fix (webhook HTTP semantics) + Milestone I (Admin dashboard visual polish)

Full backend regression **304 / 304** pytest green (+29 iteration14 advisory
tests). Independently verified in iterations 14 + 15 — zero critical/minor
issues, zero action_items.

### Advisory fix — webhook HTTP semantics
Aligned webhook verification failures with the existing INTERNAL_SERVICE_TOKEN
convention. **Never 500, never 2xx.**

- `routers/webhooks_email.py` — explicit allow-set:
  `_SERVER_MISCONFIG = {"webhook_secret_not_configured", "webhook_public_key_not_configured"}`
  → HTTP **503**. Anything else → HTTP **400**.
- `routers/webhooks_payment.py` — split allow-set:
  - `_SERVER_MISCONFIG_EXACT = {"webhook_secret_not_configured", "webhook_id_not_configured"}`
  - `_SERVER_MISCONFIG_PREFIX = ("auth_failed", "upstream_error")` — for
    PayPal's server-to-server verification round-trip.
  Both branches → HTTP **503**. Everything else (missing/invalid headers,
  bad signature, stale timestamp, malformed body) → HTTP **400**.
- Unknown provider slug → HTTP **404** (unchanged).

Live-preview curl matrix confirmed all six webhook routes return 503 for
server-misconfig, 404 for unknown slug, never 500/2xx.

### Milestone I — Admin Integrations dashboard visual polish
**Behaviour-neutral.** Zero endpoint changes, zero RBAC changes.

- `StatusChip` component — 5 accessible chips (Connected / Test mode /
  Configuration required / Degraded / Disabled). Each with a colored dot +
  ring + subtle background; AA contrast in light AND dark modes.
- `CopyableCode` component — webhook URL panel now has a Copy button that
  writes to clipboard with a 1.6s "Copied" affordance.
- Category grouping in stable order (auth → ai → payments → email → sms →
  voice → storage → misc) with icons + provider counts.
- Missing env vars rendered as red-tinted monospace pills (was: bare
  divs) — scannable at a glance.
- Test button now has an inline loading spinner + per-row result badge
  (`✓ Nms` on success, `✗ failed` on failure) — replaces the old global
  flash-only feedback.
- Support role: Actions cell now renders a literal `read-only` span
  (`data-testid=integration-actions-readonly-{slug}`) instead of
  visually-clickable-but-disabled Test/Disable buttons. Backend still
  returns 403 for any mutation attempt.
- Category testids upgraded to UPPERCASE for consistency with the
  status-enum convention:
  `integrations-category-{AUTH,AI,PAYMENTS,EMAIL,SMS,VOICE,STORAGE}`.
- Responsive: missing-env column collapses on mobile; missing-env pills
  stack under the provider label on narrow viewports.

### Data-testid contract (unchanged from Milestone A, one addition)
`admin-integrations-tab`, `admin-tab-integrations`, `integrations-summary`,
`integrations-summary-{STATUS_UPPER}`, `integrations-category-{CAT_UPPER}`,
`integration-row-{slug}`, `integration-status-{slug}`,
`integration-open-{slug}`, `integration-test-{slug}` (admin only),
`integration-toggle-{slug}` (admin only),
`integration-actions-readonly-{slug}` (support only · NEW),
`integration-detail-modal`, `integration-webhook-url`,
`integration-webhook-url-copy`.

### Tests
- Updated `tests/test_iteration13_indep_verification.py` to expect
  HTTP 503 (was 500) for webhook secret-not-configured cases.
- Updated `tests/test_milestone_h_webhooks.py` similarly.
- Added `tests/test_iteration14_advisory_fix.py` (22 tests) and
  `tests/test_iteration15_advisory_fix_hardened.py` (19 tests) as
  regression fixtures.


## 2026-02-21 · Founder integrations mandate — Milestone H (Payment webhooks + ElevenLabs + admin polish)

Full regression **275 / 275** pytest green (+9 Milestone H tests). All eight
milestones (A → H) of the founder integrations mandate now shipped.

### Payment webhook route
- `routers/webhooks_payment.py` → `POST /api/webhook/payment/{provider_slug}`.
  Dispatches to `stripe` / `razorpay` / `paystack` / `paypal` adapters via
  their `verify_webhook()` methods. Handles async adapters (PayPal) and
  sync ones (Stripe / Razorpay / Paystack).
  Hard-fail:
  - 400 on invalid signature or malformed timestamp.
  - 500 on missing vendor secret (never a silent bypass).
  - 404 on unknown provider slug or non-payment category.
- Dedup: `_extract_external_event_id()` pulls the vendor's canonical event
  id (Stripe `id`, Razorpay `payload.payment.entity.id`, Paystack
  `data.id`, PayPal `id`), falls back to a SHA-256 body hash. Combined
  with the `webhook_events(provider, external_event_id)` unique index,
  replays return `status=duplicate`.
- Wired into `server.py` alongside the email webhook router.

### ElevenLabs adapter
- `integrations/voice/elevenlabs_provider.py` promoted from stub:
  - `text_to_speech(text, voice_id, model_id)` — real
    `POST /v1/text-to-speech/{voice_id}` call returning MP3 bytes.
    Requires `ELEVENLABS_API_KEY` + a resolved voice id.
  - `test_connection()` hits `/v1/user` (auth-only, no cost).
  - Hard-fails with `configuration_required` when credentials are missing.

### Admin dashboard functional polish
- `routers/integrations.py::get_integration` now surfaces a
  `webhook_url` field on payment + email provider detail responses so
  ops can copy/paste the URL into the vendor dashboard. Uses
  `X-Forwarded-Proto` / `X-Forwarded-Host` to render the external URL
  rather than the internal cluster hostname.
- `frontend/src/pages/Admin.jsx` — new detail-modal panel renders the
  webhook URL with `data-testid="integration-webhook-url"`.

### Tests
- `tests/test_milestone_h_webhooks.py` — 9 tests:
  - Unknown payment provider → 404.
  - Stripe route hard-fails (400/500) when `STRIPE_WEBHOOK_SECRET`
    unset.
  - ElevenLabs CONFIGURATION_REQUIRED status.
  - ElevenLabs `text_to_speech()` hard-fails without credentials.
  - `_extract_external_event_id` correctness for Stripe / Razorpay /
    Paystack styles + hash fallback on unparseable bodies.


## 2026-02-21 · Founder integrations mandate — Milestone G (AI gateway strangler)

Full regression **266 / 266** pytest green (+5 AI gateway tests). Existing
`services/llm.py` (Phase 2 canonical LLM path) is unchanged — strangler
migration is opt-in.

### AI gateway
- `services/ai_gateway.py` — unified single-turn `chat()` router.
  Selects the AI adapter by slug (`openai` / `anthropic` / `gemini`),
  delegates to `provider.chat()`, and records a cost row to
  `llm_costs` (`gateway: "ai_gateway.v1"`). Hard-fails with
  `unknown_ai_provider` for unknown slugs or non-AI categories.
  Cost is recorded on both success AND failure paths.

### Adapter uplifts
- `integrations/ai/_shared.py` — new `emergent_chat_singleturn()` helper
  that wraps the emergentintegrations `LlmChat` boundary exactly once.
  Every AI adapter delegates here. Hard-fails with
  `ProviderError("configuration_required")` when `EMERGENT_LLM_KEY`
  is unset.
- `integrations/ai/openai_provider.py`,
  `integrations/ai/anthropic_provider.py`,
  `integrations/ai/gemini_provider.py` — real `chat()` methods.
  `test_connection()` asserts SDK importability + non-empty key.
  Truthful `TEST_MODE` status when EMERGENT_LLM_KEY is set.

### Tests
- `tests/test_milestone_g_ai_gateway.py` — 5 tests:
  - Gateway routes to OpenAI adapter + records cost row on success.
  - Gateway records cost row on failure.
  - Adapter `chat()` hard-fails without `EMERGENT_LLM_KEY`.
  - Unknown slug → `unknown_ai_provider`.
  - Non-AI slug (`stripe`) → `unknown_ai_provider`.


## 2026-02-21 · Founder integrations mandate — Milestone F (Payments · strangler + regional adapters)

Full regression **261 / 261** pytest green (+16 payments tests). Adapters
promoted from stubs to real code paths; existing v0.1 billing service left
untouched (strangler-ready — adapter methods can be swapped in later).

### Shared crypto primitives
- `integrations/payments/signature_verifiers.py`:
  - `verify_stripe_signature()`   — HMAC-SHA256 over `{ts}.{raw_body}` in
    the `Stripe-Signature` header (parses `t=` / `v1=`; 5-min replay window).
  - `verify_razorpay_signature()` — HMAC-SHA256 hex over `raw_body`.
  - `verify_paystack_signature()` — HMAC-SHA512 hex over `raw_body`.
  - All three hard-fail on `webhook_secret_not_configured` /
    `missing_signature_header` / `invalid_signature` /
    `timestamp_out_of_tolerance`. No bypass mode.

### Adapter uplifts
- **Stripe** (`integrations/payments/stripe_provider.py`):
  `create_checkout_session()` thin adapter over the emergent SDK +
  `verify_webhook()` that runs **independent** cryptographic verification
  (via the shared helper). Legacy `domains/billing/service.py` is
  untouched — strangler migration is opt-in.
- **Razorpay** (`integrations/payments/razorpay_provider.py`):
  `create_order()` calls `POST /v1/orders` with Basic auth;
  `test_connection()` hits `/v1/payments?count=1`; `verify_webhook()`
  wraps the SHA-256 helper.
- **Paystack** (`integrations/payments/paystack_provider.py`):
  `initialize_transaction()` calls `POST /transaction/initialize` with
  Bearer auth; `test_connection()` hits `/balance`; `verify_webhook()`
  wraps the SHA-512 helper (uses the secret key when a dedicated
  webhook secret is not set — per Paystack docs).
- **PayPal** (`integrations/payments/paypal_provider.py`):
  `_get_access_token()` handles the sandbox/live OAuth exchange;
  `create_order()` calls `POST /v2/checkout/orders`;
  `verify_webhook()` performs the required server-to-server
  `POST /v1/notifications/verify-webhook-signature` round-trip —
  hard-fails on missing `PAYPAL_WEBHOOK_ID`, missing signature headers,
  or `verification_status != SUCCESS`.

### Tests
- `tests/test_milestone_f_payments.py` — 16 tests:
  - Status matrix (stripe TEST_MODE; regionals CONFIGURATION_REQUIRED).
  - `create_order` / `initialize_transaction` / `create_checkout_session`
    hard-fail without credentials.
  - Stripe / Razorpay / Paystack signature verification (valid / missing
    secret / missing header / bad signature / stale timestamp).
  - PayPal hard-fail on missing `PAYPAL_WEBHOOK_ID` / missing headers.


## 2026-02-21 · Founder integrations mandate — Milestone E (Google Sign-In · Emergent-managed)

Full regression **245 / 245** pytest green (+7 Google tests). Google Sign-In
is wired end-to-end (backend + frontend) using Emergent's managed OAuth
service. Because Emergent handles the OAuth handshake there is no per-app
client secret — the adapter reports `CONNECTED` (or `TEST_MODE` if the
operator sets `GOOGLE_AUTH_TEST_MODE=true`).

### Backend
- `domains/auth/google_service.py`:
  - `start_google_session(session_id)` — server-to-server exchange with
    `https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data`.
    Returns either `status=logged_in` (session cookie set) OR
    `status=pending_consent` with a short-lived `pending_signup_id`.
    Consent-first invariant enforced: NO user row created until the
    consent scopes are submitted.
    Rate-limited per IP + partial-session-id bucket to defeat replay.
    401 / 404 upstream → 401 downstream (never a raw 502 leak).
  - `complete_google_signup(pending_signup_id, consents,
    policy_text_version)` — requires all `REQUIRED_SCOPES`, records every
    scope in the consent ledger, upserts the `linked_auth_identities`
    row, and mints the standard `oppos_session` cookie via the same code
    path as password login.
- `domains/auth/router.py`:
  - `POST /api/v1/auth/google/session`.
  - `POST /api/v1/auth/google/complete`.
- CSRF middleware exempts these two endpoints (same rationale as
  `/login` and `/signup` — no session cookie exists yet).
- Startup adds unique indexes on
  `linked_auth_identities(provider, provider_user_id)` +
  `(provider, email)` and a TTL index on `pending_google_signups.expires_at`.
- Audit events: `auth.google_pending_signup`, `auth.google_signup`,
  `auth.google_login`, `auth.account_link`, `auth.session_created`.

### Provider adapter
- `integrations/auth/google_provider.py` upgraded from stub. Reports
  `CONNECTED` by default (Emergent-managed → no per-app secret required).
  Optional env `GOOGLE_AUTH_ENABLED=false` flips the adapter to
  `CONFIGURATION_REQUIRED` for a hard rollout kill-switch. `test_connection()`
  pings the session-data endpoint (a 4xx is a healthy signal because the
  endpoint requires `X-Session-ID`).

### Frontend
- `lib/auth.jsx` — `googleStart()` / `googleExchange(sessionId)` /
  `googleCompleteSignup(...)` added to the shared context.
- `pages/GoogleCallback.jsx` — mounted at `/auth/callback`. Extracts
  `#session_id=<sid>` from the URL fragment, cleans the fragment, exchanges
  the session, and either navigates to `/settings` on login OR renders the
  five-scope consent form on pending_consent. `data-testid` coverage:
  `google-callback`, `google-checking`, `google-error`,
  `google-consent-form`, `google-consent-{scope}`, `google-consent-submit`.
- `pages/Login.jsx` — new "Continue with Google" button
  (`data-testid="google-signin-btn"`).
- `pages/Signup.jsx` — new "Continue with Google" button
  (`data-testid="google-signup-btn"`).

### Tests
- `tests/test_milestone_e_google.py` — 7 tests:
  - Provider status matrix (CONNECTED default, CONFIGURATION_REQUIRED when
    disabled by operator).
  - Consent-first invariant on unknown email.
  - Existing-user linking + login on Google flow.
  - Invalid session_id → 401.
  - Missing required consent → 400 `required_consent_missing`.
  - Happy-path signup creates user + link + consent ledger + session cookie.
  - Sensitive tokens (`session_token`) never surface in the response body.


## 2026-02-21 · Founder integrations mandate — Milestone D (Twilio Verify · OTP)

Full regression **238 / 238** pytest green (+7 twilio tests). Twilio Verify
adapter promoted from stub to production-shaped code path. Provider stays
`CONFIGURATION_REQUIRED` in preview because no `TWILIO_*` env vars are set.

### Adapter
- `integrations/sms/twilio_provider.py`:
  - `start_verify(to, channel)` → `POST /Services/{sid}/Verifications`
    via httpx with basic auth (SID + auth token).
  - `check_verify(to, code)` → `POST /Services/{sid}/VerificationCheck`;
    returns `{approved: bool, status, sid}`.
  - Both hard-fail on `configuration_required`; no bypass mode.
  - `test_connection()` fetches the Verify service metadata (auth-only,
    no message-send cost).
  - `verify_webhook_signature(url, form_params, header_signature)`
    implements Twilio's canonical HMAC-SHA1 (`URL + sorted key+value
    pairs`) with hard-fail on missing token or bad signature.

### Tests
- `tests/test_milestone_d_twilio.py` — 7 tests:
  - CONFIGURATION_REQUIRED status matrix.
  - Hard-fail on `start_verify` / `check_verify` without keys.
  - Signature verifier: missing token / missing header / valid sig / bad sig.


## 2026-02-21 · Founder integrations mandate — Milestone C (Email · Resend + SendGrid)

Full regression **231 / 231** pytest green (+14 email tests). No real vendor
credentials in preview — both providers remain `CONFIGURATION_REQUIRED`, but
the full code paths are live and covered by cryptographic-boundary tests using
locally-generated secrets / ECDSA keypairs.

### Provider adapters
- `integrations/email/resend_provider.py` — `send()` + `verify_webhook()`
  implemented per playbook. Hard-fails without `RESEND_API_KEY` /
  `RESEND_FROM_EMAIL` / `RESEND_WEBHOOK_SECRET`. `test_connection()` hits
  Resend `/domains` (auth-only, no send cost).
- `integrations/email/sendgrid_provider.py` — `send()` + `verify_webhook()`
  implemented per playbook. Requires
  `SENDGRID_API_KEY` / `SENDGRID_FROM_EMAIL` /
  `SENDGRID_WEBHOOK_VERIFICATION_KEY` (PEM). `test_connection()` calls
  `/v3/user/profile`.

### Shared signature primitives
- `integrations/email/webhook_verifiers.py`:
  - `verify_svix_signature()` — Resend / Svix HMAC-SHA256 over
    `{svix-id}.{timestamp}.{raw_body}` with 5-minute replay tolerance.
  - `verify_sendgrid_signature()` — Twilio SendGrid ECDSA P-256 over
    `timestamp + raw_body` with 5-minute replay tolerance.
  - Both hard-fail on missing secret / bad timestamp / bad signature. No
    bypass mode.

### Webhook route
- `routers/webhooks_email.py` → `POST /api/webhook/email/{provider}`.
  Dispatches to the provider adapter's `verify_webhook()`; on success writes
  a dedup row into `webhook_events` (unique on
  `(provider, external_event_id)`); on failure returns HTTP 400/500 and
  records a `webhook_rejected` event on the admin timeline. CSRF middleware
  exempts `/api/webhook/*`; auth is by signature, not by cookie/JWT.
- Live curl smoke: unconfigured `resend` returns HTTP 500 with
  `webhook_verification_failed` / `webhook_secret_not_configured`. Unknown
  provider returns HTTP 404.

### Tests
- `tests/test_milestone_c_email.py` — 14 tests covering:
  - `CONFIGURATION_REQUIRED` status when keys are unset.
  - Send hard-fail when keys are unset.
  - Svix signature verification (valid / missing-headers /
    bad-signature / stale-timestamp / missing-secret).
  - ECDSA SendGrid verification (valid / bad-signature / missing-key).
  - Route-level hard-fail semantics through the provider verifier.

### Emergent email provider
- Playbook confirms **No Emergent email provider** — proceed with vendor
  adapters only.


## 2026-02-21 · Founder integrations mandate — Milestone B (Emergent object storage)

Full regression **217 / 217** pytest green (Milestone A tests + 4 new Milestone B tests).

### Adapter — production-grade
- `services/storage.py` now exposes two backends implementing the same
  `StorageService` protocol:
  - `EmergentObjectStorage`: talks to the Emergent object-storage playbook
    (`/init` session-scoped `X-Storage-Key`, PUT `/objects/{path}`, GET
    `/objects/{path}`). Handles 403 by re-`/init` and retrying once. Handles
    409 as idempotent write. No delete API (playbook constraint) → the method
    is a documented no-op; hard-delete lives at the DB soft-delete layer.
  - `LocalDiskStorage`: unchanged v0.1 behaviour; retained as a labelled
    fallback for containers without `EMERGENT_LLM_KEY`.
- Selection order (env-driven, no manual code changes needed):
  1. `MEDIA_STORAGE_BACKEND=local` → force local disk.
  2. `MEDIA_STORAGE_BACKEND=emergent` → force Emergent (falls back to local
     with a WARN log if the key is unset — safe for dev containers).
  3. Auto: Emergent when `EMERGENT_LLM_KEY` is present, else local disk.
- Callers (`domains/documents/service.py`, `domains/applications/service.py`)
  are untouched; the singleton `storage` picks the right backend at import
  time.

### Provider — truthful admin surface
- `integrations/storage/media_storage_provider.py` upgraded from a stub:
  - `required_env=("EMERGENT_LLM_KEY",)`; `optional_env=("MEDIA_STORAGE_BACKEND",)`.
  - `validate_configuration()` respects a `MEDIA_STORAGE_BACKEND=local`
    override (surfaces the ops-required env var name for the production
    backend even when running on local disk).
  - `health_check()` is a side-effect-free probe that reads the singleton
    backend name — sub-2s, no network.
  - `test_connection()` runs a real `/init` round-trip (Emergent) or a
    write+read probe (local disk) so admins can validate live from the
    dashboard.
- Status matrix now truthfully shows `media_storage=TEST_MODE` when the key is
  present; falls back to `CONFIGURATION_REQUIRED` on production deploys with
  the key unset.

### Constraints from the Emergent playbook (enforced in code)
- **No delete API** — soft-delete stays a DB-layer concern (`documents.deleted_at`).
- **No presigned URLs** — every download stays proxied through the backend.
- **Session-scoped `storage_key`** — refresh on HTTP 403, cached in-memory.
- **Path prefix** — every object key is prefixed with `opportunityos/` before
  hitting the vendor.

### Verified live round-trip
Round-trip PUT + GET tested end-to-end (`test_put_get_roundtrip`) against the
live Emergent bucket. SHA256 verified stable across write/read.


## 2026-02-21 · Founder integrations mandate — Milestone A (foundation)

Independent verification: `/app/test_reports/iteration_12.json` — 23 new tests in
`/app/backend/tests/test_milestone_a_integrations.py` + 5 integrations tests inside
`/app/backend/tests/test_security_invariants.py`. Full backend regression 190/190 green
(after conftest was updated to purge `login_throttle` for known test accounts).

### Foundation code
- `backend/integrations/base.py` — `ProviderStatus` enum (CONNECTED, TEST_MODE,
  CONFIGURATION_REQUIRED, DEGRADED, DISABLED), `ProviderCategory`,
  `ConfigValidation`, `HealthResult`, `TestResult`, `ProviderError`, `BaseProvider`
  contract.
- `backend/integrations/registry.py` — auto-loads adapter modules at startup,
  exposes `get/all/by_category/summary`, guards against broken adapters.
- `backend/integrations/health.py` — `snapshot_provider`, `record_event`,
  `run_health_checks`, `ensure_indexes` (`integration_configs`,
  `integration_events`, `webhook_events` unique on (provider, external_event_id)).

### Adapters registered (14) — actual runtime slugs
- **Payments**: `stripe`, `razorpay`, `paypal`, `paystack`
- **Auth**: `email_password`, `google_auth`
- **Email**: `resend`, `sendgrid`
- **SMS**: `twilio`
- **AI**: `openai`, `anthropic`, `gemini`
- **Voice**: `elevenlabs`
- **Storage**: `media_storage`

Verified runtime status matrix:
- **CONNECTED**: `email_password`
- **TEST_MODE**: `stripe`, `openai`, `anthropic`, `gemini`, `media_storage`
- **CONFIGURATION_REQUIRED**: `google_auth`, `resend`, `sendgrid`, `twilio`,
  `elevenlabs`, `razorpay`, `paypal`, `paystack`
- All 14 truthfully report required env-var names in `missing_env`. No secret
  values ever surface in `describe()`.

### Admin router — `/api/v1/admin/integrations`
- `GET /` — admin+support read, returns providers + summary counts.
- `GET /{slug}` — admin+support read, adds `recent_events` (last 20).
- `POST /{slug}/test` — admin-only, calls `provider.test_connection()`, records
  event, updates snapshot, writes audit row.
- `POST /{slug}/enable` / `POST /{slug}/disable` — admin-only, records event +
  audit row. Support gets 403.
- CSRF double-submit is enforced by the global `CSRFMiddleware` on every
  state-changing verb; browser sessions cannot mutate integration state without
  the `X-CSRF-Token` header.

### Admin UI — Integrations tab
- New tab in `frontend/src/pages/Admin.jsx` (`IntegrationsTab`). Groups the 14
  providers by category, renders status pill, missing-env list, per-row Test /
  Enable/Disable buttons (support role sees the disabled state), and a detail
  modal showing recent events. Data-testid attributes:
  `admin-integrations-tab`, `integrations-summary`, `integration-row-{slug}`,
  `integration-status-{slug}`, `integration-test-{slug}`,
  `integration-toggle-{slug}`, `integration-detail-modal`.

### Regression hardening
- `backend/tests/conftest.py` autouse now purges `login_throttle` for the four
  well-known test accounts (fixture-ead, ujjwal, admin, support) at every
  module boot so the SEC-P3(a) throttle no longer poisons the full pytest sweep
  (the dedicated `TestLoginThrottle` test uses a unique random email + explicit
  cleanup and is unaffected).

### Known deltas from the review spec
- Google Auth provider slug is `google_auth` (spec said `google_oauth`) — docs
  aligned here; no rename because that would invalidate the persisted
  `integration_configs` snapshot.
- Anonymous callers to a mutation endpoint receive HTTP 403 (`csrf_invalid`)
  ahead of the 401 auth check, because CSRF middleware runs before the auth
  dependency. Access is still refused; semantics are safe.


## 2026-02-20 · Security audit remediation — SEC-001..004 + P3

Post-`v0.1 CERTIFIED` remediation of the four Medium findings from the security audit + two P3 hardening items. Full backend regression **182/182 pytest green**.

### SEC-001 · Privacy export leaked own `password_hash` — FIXED
- `domains/privacy/service.py::_build_bundle` now reuses `_sanitize_user()` + `SENSITIVE_USER_FIELDS` from `domains/admin/service.py` (single source of truth) and applies the same projection at the driver level.
- Regression: `TestPrivacyExportDoesNotLeakCredentials` asserts absence of `password_hash`/`password`/`totp_secret`/`recovery_codes` keys AND the bcrypt marker regex in the serialized export body.

### SEC-002 · Password change did not invalidate sibling sessions — FIXED
- `domains/users/service.py::change_password` now (1) revokes ALL sessions for the user via `sessions.revoke_all_for_user`, (2) if the caller is on the cookie path, mints a fresh session in-place so they stay logged in (anti-fixation).
- Regression: `TestSiblingSessionRevocationOnPasswordChange` opens two sessions, rotates the password in A, asserts A survives and B returns 401 on `/auth/me`.

### SEC-003 · Idempotency collapsed cookie-auth callers to `anon` — FIXED
- `middleware/idempotency.py` now resolves the caller in this order: cookie session → Bearer JWT → IP-scoped `anon:{ip}`. Two cookie-authenticated users hitting the same endpoint with the same `Idempotency-Key` are guaranteed distinct executions.
- Regression: `TestIdempotencyIsUserScopedOnCookiePath` posts identical Idempotency-Keys to `/consents` from two sessions and asserts distinct `id` values in the response bodies.

### SEC-004 · Deploy-flag disclosure + preview posture — code parts FIXED
- (a) `access_token` in login/signup body was already gated by `CI_TEST_ISSUER_ENABLED` via `_maybe_bearer_body` — added a monkeypatched pure-unit test asserting the helper returns `{}` when the flag is off. Live preview keeps the flag on so pytest continues to work with Bearer.
- (b) CORS: `server.py` strips `localhost` / `127.0.0.1` from the allowlist when `PROD_MODE=true`. In PROD_MODE the server refuses to start with an empty `CORS_ALLOW_ORIGINS`.
- (c) `JWT_SECRET` rotated to a fresh 64-byte urlsafe secret (invalidates all existing sessions — accepted at v0.1). `backend/.env` and `frontend/.env` removed from git's index (`git rm --cached`); `.gitignore` entries already in place, verified.
- (d) Public `/api/health` no longer returns `prod_mode` / `ci_test_issuer_enabled`. Those flags now live on the admin-only `/api/v1/admin/health` endpoint.

### P3(a) · Login-brute-force throttle — ADDED
- `services/login_throttle.py`: sliding-window per (route, identifier) capped at 10 attempts / 5 min AND per (route, ip) at 30 attempts / 5 min. Either → 429 with `Retry-After`. `X-Forwarded-For` respected so k8s ingress round-robin can't defeat the counter. Successful login clears the identifier bucket.
- Wired into `/api/v1/auth/signup` and `/api/v1/auth/login`. Indexes ensured at startup.
- Regression: `TestLoginThrottle` proves 429 with `Retry-After` header within the max window.

### P3(b) · Frontend scheme allowlist — ADDED
- New helpers `safeExternalHref` / `safeAssign` in `frontend/src/lib/utils.js`. Only `http:` / `https:` accepted; `javascript:` / `data:` / `vbscript:` / etc. are refused with a console warning.
- Wired into `pages/JobDetail.jsx:184`, `pages/Feed.jsx:631`, `pages/Billing.jsx:79` (Stripe checkout redirect).

### Pre-prod checklist — status by item

| Item | v0.1 code-enforced? | Deploy-time flip still required? |
|---|---|---|
| Access-token in body | YES (off when CI flag off) | Flip `CI_TEST_ISSUER_ENABLED=false` on prod |
| Public health flag disclosure | YES (stripped unconditionally) | — |
| CORS localhost in PROD_MODE | YES (stripped at boot) | Set `PROD_MODE=true`, tighten `CORS_ALLOW_ORIGINS` to prod host |
| JWT secret strength | YES (rotated to 64-byte random) | Rotate again on prod deploy for extra hygiene |
| `.env` in git tracking | YES (`git rm --cached`; .gitignore in place) | Verify on prod that `.env` still ignored |
| Fail-fast on `PROD_MODE + CI_TEST_ISSUER_ENABLED` | YES (server refuses to boot) | — |
| CORS empty allowlist in PROD_MODE | YES (server refuses to boot) | Set the env var before boot |



## 2026-02 · Phase 6 — Billing / Privacy / Admin / Auth hardening

### Billing (S19)
- Stripe TEST-mode integration via `emergentintegrations` (Flow B).
- Checkout / cancel / refund / invoices + FOUNDER19 coupon.
- Plan caps: `jobs_processed` (hourly), `applications_prepared` (monthly), `apps_submitted` (daily).
- Frontend `Billing.jsx`: current-plan card, three usage meters with verbatim definitions, ≤2-click cancel, 7-day auto-refund action, invoice list.

### Privacy (S20)
- Consents view + revoke (append-only record).
- Data-release log rendered from receipts.
- JSON data-export bundle (self-service, downloads client-side).
- Account soft-delete → 30-day window with restore on next sign-in; hard-sweep on startup.

### Admin console (S18)
- `Admin.jsx` full 7-tab console: Users, Subscriptions, Manual queue, Feature flags, Support tickets, Health, Observability.
- Sealed values MASKED with **no unmask capability** anywhere in v0.1.
- Every user-detail view writes an `admin.user_detail_view` audit row.
- Refunds require reason enum + optional note. All flag mutations audited with `changed_by`.
- Support role = **READ-ONLY** everywhere except support tickets (server-side enforced via `_require_admin_only` on write endpoints).

### Auth hardening
- Server-side session store: new `sessions` collection (unique on `session_id`, TTL on `expires_at`). Login inserts a fresh row; logout revokes; role change rotates (`rotate_session`).
- `oppos_session` cookie: httpOnly, Secure, SameSite=**Lax** for user roles / **Strict** for admin+support.
- `oppos_csrf` cookie: JS-readable, same SameSite, echoed to `X-CSRF-Token` on every state-changing verb via axios interceptor.
- `middleware/csrf.py`: double-submit enforcement on `POST/PUT/PATCH/DELETE` under `/api/v1/*`. Exempt: `GET/HEAD/OPTIONS`, `/api/internal/*` (X-Service-Token), `/api/webhook/*`, `/api/v1/auth/login`, `/api/v1/auth/signup`.
- `core/deps.py::get_current_user`: cookie session first; Bearer JWT ONLY if `CI_TEST_ISSUER_ENABLED=true`.
- `core/config.py`: new settings `PROD_MODE`, `CI_TEST_ISSUER_ENABLED`, `SESSION_*`, `CSRF_*`, `CORS_ALLOW_ORIGINS`. Server refuses to start if `PROD_MODE && CI_TEST_ISSUER_ENABLED`.
- CORS: explicit origin allowlist with `allow_credentials=True`. Wildcard fallback only when the env var is empty and credentials disabled.
- Frontend: `localStorage['oppos.token']` removed entirely. `api.js` uses `withCredentials: true` + a request interceptor that reads the CSRF cookie and injects the header on state-changing verbs. `auth.jsx` no longer stores or reads any token — session lives fully server-side.

### Cleanup
- Deleted stub `domains/admin/router.py` and `domains/admin/models.py` (replaced by full `domains/admin/service.py`).
- Removed duplicate `app.include_router(admin_router)` in `server.py`. Added a startup check that fails-fast on duplicate FastAPI operation IDs (`_assert_unique_operation_ids`).
- Removed dead placeholder Billing/Privacy imports from `App.js`.
- Purged legacy `feature_flags.key` schema (unique index dropped in Mongo, `ensure_indexes` no longer recreates it). Seeder migrated to `{name, enabled, description}`.

### Auth-model change for CI scripts
- Pytest suites continue to use Bearer with `access_token` from the login response — this only works because `.env` sets `CI_TEST_ISSUER_ENABLED=true` in preview. In prod that flag MUST be false and pytest MUST switch to a cookie-based `httpx.AsyncClient(cookies=…)` flow (or run against a preview instance with the CI flag on). `_login()` helper in `tests/test_phase5_e2e.py` and `tests/test_phase3_integration.py` continues to work as-is.

### Deprecations / removed
- `frontend/src/pages/placeholders.jsx` and `frontend/src/components/PhasePlaceholder.jsx` deleted (no more phase-preview stubs; real pages ship for every route).

### Bug fixes surfaced by Acceptance Run A–I
- `domains/admin/service.py::system_health` counted a non-existent `audit_events` collection. Renamed to the actual `audit_logs` collection so the count reflects the real (append-only) audit ledger.
- `domains/privacy/service.py` export bundle fetched `audit_trail` from `audit_events` with `{actor_id: user_id}`. The real collection is `audit_logs` with field `actor`. Corrected. The Phase 6 export now returns the user's real audit trail (>2000 rows for fixture-ead).
- `tests/test_fixture_acceptance_b.py::test_usage_meter_starts_at_zero` was still asserting the pre-Phase 6 scalar meter shape. Updated to accept the new `{used, cap, resets_at, meter}` dict.
- `components/Topbar.jsx::UsageMeterChip` rendered `{usage.jobs_processed}` — now an object per Phase 6 caps refactor — causing a React "Objects are not valid as a React child" crash on every authenticated page. Normalised to `.used`.

### Final acceptance run
- 153/153 backend pytest green (119 prior + 34 new phase-6 acceptance tests). 100% A–I pass. Screenshots at `/app/test_reports/p6-*.png`. Detailed report at `/app/test_reports/p6-acceptance-run.md`.

### v0.1 close-out fix directive (post-acceptance)
- **P0 SECURITY** — `/api/v1/admin/users/{id}` was returning the target user's raw `password_hash` (bcrypt). Added `SENSITIVE_USER_FIELDS = {"password_hash", "password", "totp_secret", "recovery_codes"}` constant + `_sanitize_user()` helper in `domains/admin/service.py`. The user projection now excludes those fields at the driver level, and the sanitizer scrubs again post-fetch (defence-in-depth). Sweep of every admin endpoint confirmed no `password_hash` / `totp_secret` / bcrypt-marker string leaks anywhere. New pytest `test_admin_user_detail_never_leaks_password_hash` locks the invariant in for both admin and support roles.
- **P1 PROVABLE SEALED MASKING** — admin user-detail now surfaces `eligibility_profile` with sealed data fields (`status`, `dates`, `notes`, `derived_flags`) replaced by the mask literal `"•••• (sealed)"` (matches PRD §Sealed fields). Sealed claims already returned the mask literal; alignment to the PRD wording is done here. Frontend `Admin.jsx` shows the new masked block. New pytest `test_admin_user_detail_masks_sealed_data` inserts a sentinel sealed claim, verifies both admin and support see the mask literal, and asserts the raw sentinel value never appears anywhere in the response body.
- Mask literal changed from `"🔒 masked (sealed sensitivity)"` to `"•••• (sealed)"` to match `PRD.md` §Sealed fields.

## 2026-02-20 · v0.1 CERTIFIED — security-invariants module (test-only)

- Added `tests/test_security_invariants.py` — parametrised regression that enumerates every admin/user response endpoint and asserts no credential/secret marker (password_hash / password / totp_secret / recovery_codes / csrf_token / session_id / `$2[aby]$` bcrypt-prefix) ever appears in a response body.
- 18/18 tests green. Full backend regression: 173/173 pytest.
- Adding a new admin/user GET endpoint from now on requires appending it to `ADMIN_READ_ENDPOINTS` or `USER_SELF_ENDPOINTS` in that module. Adding a new credential column on `users` requires appending it to `CREDENTIAL_KEYS`.
- `test_admin_service_lists_all_known_credential_fields` cross-checks that `SENSITIVE_USER_FIELDS` in `domains/admin/service.py` stays in sync with the invariants registry.

**v0.1 close-out complete.** Final commit: recorded at write-time.
