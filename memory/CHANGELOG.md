# OpportunityOS — CHANGELOG

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
