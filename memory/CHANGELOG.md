# OpportunityOS — CHANGELOG

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
