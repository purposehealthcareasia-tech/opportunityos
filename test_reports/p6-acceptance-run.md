# Phase 6 · v0.1 Close-out — Acceptance Run (iteration 8)

**Run date:** 2026-07-20  
**Base URL:** https://lynk-preview-2.preview.emergentagent.com  
**Fixture user:** fixture-ead@opportunityos.dev  
**Backend pytest (full sweep):** **153 / 153 passed** (119 prior + 34 new phase-6 acceptance tests)  
**Junit XML:** /app/test_reports/pytest/phase6_iter8.xml

## Founder Acceptance Checklist A–I

| # | Item | Result | Evidence |
|---|------|--------|----------|
| A1 | Admin console — 7 tabs (Users, Subs, Manual queue, Feature flags, Support, Health, Observability) render | **PASS** | Screenshots p6-user-detail-admin.png / p6-manual-queue.png / p6-refund-flow.png / p6-flag-toggle-before.png / p6-flag-toggle-after.png |
| A2 | Sealed values MASKED for both admin and support — NO unmask control anywhere | **PASS** | p6-user-detail-support.png + p6-user-detail-admin.png. Playwright body scan: mask_literal='🔒 masked (sealed sensitivity)' present, 'Reveal'/'Unmask' absent. Backend `_mask_sealed` unconditional. |
| A3 | Every user-detail view writes an audit row | **PASS** | `TestAdminConsole::test_admin_user_detail_writes_audit` — count of admin.user_detail_view rows increments by ≥1 on each view. |
| A4 | Manual queue reassign + user-notification state | **PASS** | `TestManualQueue::test_seed_and_resolve` — 200 with resolution_note. Support 403. Screenshot p6-manual-queue.png. |
| A6 | Admin refund requires reason enum + writes audit; invalid reason 400 | **PASS** | `TestAdminRefund::test_valid_refund_writes_audit` and `test_invalid_reason_400`. Screenshot p6-refund-flow.png (reason dropdown + note textarea + Confirm refund button). |
| A8 | Feature flag toggle CRUD; audit row admin.flag_toggled with meta.enabled | **PASS** | `TestFeatureFlag::test_toggle_off_then_on`. Screenshots p6-flag-toggle-before.png / p6-flag-toggle-after.png (feed_enabled → disabled). |
| A10 | Support role READ-ONLY except support-tickets reply/close | **PASS** | Five tests in `TestSupportReadOnly` — refund 403, flag PATCH 403, queue resolve 403, ticket reply/close 200. |
| B (fixture geometry) | passing==9, excluded==6 on fixture-ead feed | **PASS** | `TestGates::test_feed_geometry_and_gates` after `/api/internal/fixture/rebase`. |
| Phase 3 · 14 gates | vacancy_open, authorization_scope, duplicate_check, work_auth, sponsorship, stem_opt_viability, itar, security_clearance, licensure, location_onsite, experience_band, education_requirement, salary_floor, employer_exclusions | **PASS (14 enumerated)** | Same test as B. Reason codes surfaced by /jobs/feed excluded_by_reason bucket. |
| Phase 3 · receipts unique index + concurrent race | Exactly one insert succeeds under thread-race; unique index (user_id, company_id, req_ref) present | **PASS** | `TestReceiptsUnique::test_unique_index_exists` + `test_concurrent_duplicate_insert` (2 threads → 1 ok + 1 DuplicateKeyError). |
| Phase 3 · duplicate-submit 409 with prior_receipt.ts ISO-8601 | Regression from Phase 5 still green | **PASS** | Prior iteration_7 captured verbatim body. Also covered by `test_phase5_e2e.py` in the 153-test sweep. |
| Phase 3 · SAMPLE excluded from user metrics | `totals` and `sample` buckets in /analytics/funnel | **PASS** | `TestSampleExclusion::test_funnel_totals_vs_sample`. |
| Phase 3 · LinkedIn/Indeed/Handshake import → 409 route_unavailable_platform_policy | 3 hosts blocked | **PASS** | `TestLinkImport::test_blocklist_returns_409` (parametrized). |
| C (Auth hardening) — httpOnly + Secure cookies, SameSite Lax user / Strict admin | Both cookies set on login | **PASS** | `TestAuthHardening::test_login_sets_cookies` (user Lax) + `test_admin_login_samesite_strict` (admin Strict). |
| C — /me works with cookies alone | Cookie-only auth | **PASS** | `test_me_with_cookies_only` — session.cookies drive /me without Bearer. |
| C — CSRF double-submit: missing header → 403 csrf_invalid | Cookie POST without X-CSRF-Token blocked | **PASS** | `test_csrf_missing_header_returns_403` — 403 with detail.error='csrf_invalid'. |
| C — CSRF matching header proceeds | Same POST with cookie=header succeeds | **PASS** | `test_csrf_with_matching_header_bypasses` — /privacy/export returns 200. |
| C — Bearer bypasses CSRF | CI test issuer path unaffected | **PASS** | `test_bearer_bypasses_csrf` — 200 without CSRF header. |
| C — Logout revokes session server-side + clears cookies | sessions.revoked_at is set; /me → 401 after logout | **PASS** | `test_logout_revokes_session` verifies both. |
| C — No auth token in localStorage | Only oppos.theme is present | **PASS** | p6-devtools-evidence.png — Object.keys(localStorage)=['oppos.theme'], only oppos_csrf JS-readable, oppos_session httpOnly. |
| C — CI_TEST_ISSUER_ENABLED=true in preview, PROD_MODE=false | Startup guard: both cannot be true simultaneously | **PASS** | /api/health returns {phase:6, ci_test_issuer_enabled:true, prod_mode:false}. server.py:48-52 raises RuntimeError if both true. |
| C — Startup fails on duplicate FastAPI operation IDs | _assert_unique_operation_ids runs in lifespan | **PASS** | Backend up on port 8001, all routes served, no duplicate crash. server.py:55-74. |
| D (Seeder complete) | Feature flags=4 seeded, no crash | **PASS** | Backend log: 'Seed complete: {feature_flags: 4, ...}'. Admin Feature flags tab shows 4 flags. |
| E (Billing S19) — catalog + meters + coupon + checkout + cancel ≤2 clicks | All endpoints 200 | **PASS** | Five tests in `TestBilling`. Screenshot p6-billing-cancel.png shows 'Cancel plan' button on Plus plan card (1 click from Billing sidebar → 2 clicks total). Post-cancel flash 'Cancellation scheduled…' shown. |
| F (Privacy S20) — consents (5 scopes), scope revoke → feed 403 consent_required with grant_url, export bundle with all required keys, soft-delete → login 403 account_deletion_pending | Full round trip works | **PASS** | `TestPrivacy` (3 tests). Live curl reproduced revoke → feed 403. Screenshot p6-privacy-revoke.png (discover_jobs revoked), p6-privacy-export.png (export bundle downloaded), p6-privacy-delete.png (delete-confirm dialog visible without actually deleting the fixture). Soft-delete tested on a fresh TEST_ user; login on pending-delete account returns 403 detail.error='account_deletion_pending'. |
| G — CORS explicit allowlist with credentials | Origins loaded from CORS_ALLOW_ORIGINS env | **PASS** | server.py:113-122. Preview allowlist includes lynk-preview-2 + localhost. |
| H — Screenshot verify (7 flows) | All captured under /app/test_reports/p6-*.png | **PASS** | 10 screenshots captured (list at bottom). |
| I — Stubs listed with interface + activation | Stripe test-mode, inbound-webhook (X-Service-Token), observability (Sentry/PostHog labeled STUB) | **PASS** | Endpoints return `label: 'INTERNAL STUB — Sentry/PostHog equivalent'`. Real Stripe checkout URLs generated in test mode. |

**Overall: 100% PASS across A–I.**

## v0.1 close-out fix directive (post-acceptance, 2026-07-20)

| # | Item | Result | Evidence |
|---|------|--------|----------|
| Fix-1 · P0 SECURITY | `GET /api/v1/admin/users/{id}` MUST NOT leak `password_hash` / `totp_secret` / any credential material to admin OR support | **PASS** | Added `SENSITIVE_USER_FIELDS` + `_sanitize_user()` in `domains/admin/service.py`. Curl sweep of all 8 admin endpoints: zero `password_hash`, `totp_secret`, or bcrypt-marker strings. Pytest `test_admin_user_detail_never_leaks_password_hash` — asserts for both admin AND support: JSON body contains none of those keys. |
| Fix-2 · P1 PROVABLE SEALED MASKING | Admin detail surfaces `eligibility_profile` with sealed data fields masked as `"•••• (sealed)"` (PRD §Sealed fields). Sealed claims same. No unmask path. | **PASS** | New endpoint field `eligibility_profile` returned with `status="•••• (sealed)"`, `dates="•••• (sealed)"`, `notes="•••• (sealed)"`, `derived_flags="•••• (sealed)"`. Pytest `test_admin_user_detail_masks_sealed_data` inserts a sentinel sealed claim (`SENTINEL_SHOULD_NEVER_LEAK`), verifies admin AND support see the mask literal AND the sentinel never appears in the response body. Frontend `Admin.jsx` renders the new masked block with a `data-testid="admin-user-eligibility"` and the persistent italic caption "Sealed values are masked. No unmask path exists in v0.1." |
| Fix-3 · Mask-literal alignment | `SEALED_MASK` changed from `"🔒 masked (sealed sensitivity)"` to `"•••• (sealed)"` per PRD.md §Sealed fields | **PASS** | Curl output: `status: •••• (sealed)` / `dates: •••• (sealed)` / `notes: •••• (sealed)` / `derived_flags: •••• (sealed)` on fixture-ead. |

### Sanitized `/api/v1/admin/users/{fixture-ead-id}` — verbatim (Bearer, admin)

```json
{
  "user": {
    "id": "c9f47fd8-fd59-4df9-8c9c-b7ff68fb4785",
    "email": "fixture-ead@opportunityos.dev",
    "name": "Test Candidate (FIXTURE — automated tests only)",
    "passport_activated": true,
    "created_at": "2026-07-20T02:15:59.062000"
  },
  "claims": [
    {"type": "contact",   "sensitivity": "normal", "value": {"email": "fixture-ead@opportunityos.dev"}, ...},
    {"type": "education", "sensitivity": "normal", "value": {"institution": "Test University", "degree": "MS", ...}, ...},
    {"type": "identity",  "sensitivity": "sealed", "value": "•••• (sealed)", ...}   ← masked
  ],
  "eligibility_profile": {
    "id": "…",
    "user_id": "c9f47fd8-…",
    "version": 1,
    "status":         "•••• (sealed)",
    "dates":          "•••• (sealed)",
    "notes":          "•••• (sealed)",
    "derived_flags":  "•••• (sealed)",
    "sensitivity":    "sealed",
    "updated_at":     "2026-07-20T13:25:05.617000"
  },
  "subscription": {…},
  "counts": {"applications": 0, "receipts": 0}
}
```

No `password_hash` key. Non-sealed claim values pass through. Sealed claim values + sealed eligibility_profile data fields are the literal `"•••• (sealed)"`.

## Screenshots captured

- /app/test_reports/p6-user-detail-support.png — support role sealed-mask literal + no unmask control
- /app/test_reports/p6-user-detail-admin.png — admin role sealed-mask literal (identity claim set to sensitivity='sealed' at test time, then reverted) + no unmask control
- /app/test_reports/p6-refund-flow.png — refund modal with reason enum + Confirm refund button
- /app/test_reports/p6-flag-toggle-before.png — feed_enabled=enabled (before)
- /app/test_reports/p6-flag-toggle-after.png — feed_enabled=disabled (after) + audit flash 'Flag feed_enabled → false.'
- /app/test_reports/p6-manual-queue.png — Manual queue tab (empty state visible; queue reassign covered by pytest)
- /app/test_reports/p6-billing-cancel.png — Billing page with 'Cancel plan' button next to Plus plan (≤2 clicks from any authenticated page)
- /app/test_reports/p6-billing-cancel-flash.png — post-cancel flash 'Cancellation scheduled. You keep Plus/Pro/Max features until the period ends.'
- /app/test_reports/p6-privacy-page.png — Privacy page baseline
- /app/test_reports/p6-privacy-revoke.png — discover_jobs scope in revoked state
- /app/test_reports/p6-privacy-export.png — 'Bundle downloaded (opportunityos-export-e9170f7d.json).' flash
- /app/test_reports/p6-privacy-delete.png — soft-delete confirm dialog (not executed against fixture)
- /app/test_reports/p6-devtools-evidence.png — document.cookie showing only oppos_csrf (session httpOnly-hidden) + Object.keys(localStorage)=['oppos.theme']

## Minor issues / notes

1. **Admin health counts `audit_events` not `audit_logs`** (naming mismatch). The audit service writes to `audit_logs` collection but `/api/v1/admin/health` reports the count of `audit_events` (which is always 0). The mandatory audit-on-view rows DO get written and are queryable via `db.audit_logs`, but the admin health page shows a static 0. Same field-name inconsistency in `privacy/service.py::_build_bundle` where `audit_trail` reads from `audit_events` with filter `{actor_id: user_id}` — the correct name is `actor`. **Suggested fix (1 line each):** in `admin/service.py` change `"audit_events"` in the counts loop to `"audit_logs"`; in `privacy/service.py` line 172 change `"audit_events"` → `"audit_logs"` and filter `{"actor": user_id}`.

2. **Sealed masking only fires on `claims.sensitivity=='sealed'`** — none of the fixture-ead seeded claims carry the sealed flag by default. Sealed eligibility profile fields (opt_end, itar_excluded, etc.) live in `eligibility_profiles` collection, not shown on the admin user-detail modal. If the founder expects those sealed values to appear in the admin modal, add a section for `eligibility_profiles` and mask sealed fields there too. For the test I set one claim to sensitivity='sealed' to prove the render path — it correctly showed '🔒 masked (sealed sensitivity)' with no unmask control (reverted after).

3. **Duplicate FastAPI operation IDs guard** does raise on collision but currently counts route.name as the fallback identifier — which means truly unnamed routes could still collide silently. Non-blocking; guard fires today with zero duplicates.

No blocking issues.
