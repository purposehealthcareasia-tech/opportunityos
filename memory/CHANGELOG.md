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
