# Test Result Log — OpportunityOS (LYNK)

## Original User Problem Statement
OpportunityOS is a candidate-fiduciary, consent-first AI job application platform. Product law: optimize for QUALIFIED INTERVIEWS, never application volume. The Career Passport (approved claims) is the ONLY factual source of truth. Nothing is processed without consent; every state-changing action is authenticated, idempotent, and audited.

PHASE 1 SCOPE = FOUNDATION ONLY. No job feed, no AI generation, no billing. Deliver:
- FastAPI backend under /app/backend with modular monolith layout (routers/services/repositories per domain).
- Auth: JWT email+password (bcrypt), roles user/support/admin via admin_users.
- Consent: 5-scope append-only ledger, require_consent dependency returning 403 consent_required.
- Idempotency middleware for state-changing endpoints.
- Audit log APPEND-ONLY for every state-changing action.
- Sealed serializer (claims with sensitivity=sealed masked for non-owners).
- Mongo schemas + indexes for: users, consent_records, authorization_scopes, audit_logs, feature_flags, admin_users, documents, claims, taxonomy, companies, jobs.
- Idempotent seed (taxonomy 13 families, 25 real companies, 15 SampleCo demo jobs, User Zero = Ujjwal Singla, admin + support users, feed_enabled flag).
- React frontend under /app/frontend (CRA). Design law: calm, precise, trustworthy, premium. Neutral palette, light+dark, no gradients / cartoons / fake urgency / fabricated stats.
- S1 Landing, S2 Signup+granular consent (none pre-checked; only process_career_data required), Login, authenticated shell with honest "coming later" placeholders for future sections, S18 Settings (profile + password + theme + live consent revoke), /admin gated to admin/support showing feature_flags READ list.

## Testing Protocol
- ALWAYS run backend tests FIRST via deep_testing_backend_v2.
- After backend passes, STOP and ask the user whether to run frontend tests via auto_frontend_testing_agent.
- NEVER invoke a frontend testing agent without explicit user approval.
- NEVER edit this Testing Protocol section.
- Before invoking any test agent, RE-READ this file.
- Do NOT re-fix issues that a testing agent already reports as fixed.
- Update only the Backend Tests / Frontend Tests / Agent Communication sections below.

## Incorporate User Feedback
- Treat user feedback as authoritative. Do not overreach past the phase brief.
- Preserve stubbed interfaces (email, analytics, error-tracking, storage) so later phases can swap implementations without churn.
- The auth module MUST stay swappable (Clerk was originally specified in docs; we deviated to internal JWT — keep it isolated).
- Consent is APPEND-ONLY. There is NO update/delete endpoint for consent_records. Ever.
- Every state-changing endpoint MUST accept Idempotency-Key and MUST write an audit_logs row.

## Backend Tests

### Main-agent curl smoke suite (Phase 1 foundation)

Base URL for external checks: `https://af7cc636-8506-4548-af82-a1a50aae0158.preview.emergentagent.com`. All checks below ran clean.

| # | Check | Method / path | Expected | Actual | Status |
|---|---|---|---|---|---|
| 1 | Backend healthy + OpenAPI reachable | `GET /api/openapi.json` | 200, non-empty spec | 200, 10247 bytes, 14 paths listed | PASS |
| 2 | Signup with only required consent | `POST /api/v1/auth/signup` (only `process_career_data:true`) | 201, JWT returned, consent rows appended | 201, JWT returned, all 5 scopes have consent_records rows (only required=granted) | PASS |
| 3 | Signup rejects when required scope missing | `POST /api/v1/auth/signup` (no consents) | 400 `required_consent_missing` | 400 with machine-readable body | PASS |
| 4 | Login / me | `POST /api/v1/auth/login`, `GET /api/v1/auth/me` | 200, correct role | User Zero role=user, admin=admin, support=support | PASS |
| 5 | Consent gate positive path | `GET /api/v1/passport/ping` with `process_career_data` granted | 200 | 200 payload | PASS |
| 6 | Consent gate negative path | Revoke scope, hit ping | 403 `{error:consent_required, scope, grant_url}` | 403 with exact machine-readable body | PASS |
| 7 | Consent gate re-grant | Grant scope again, hit ping | 200 | 200 | PASS |
| 8 | Append-only ledger holds | `consent_records` for revoked+regranted scope | 3 rows (seed + revoke + re-grant) | 3 rows | PASS |
| 9 | Idempotency replay | Two identical `POST /api/v1/consents` with same `Idempotency-Key` | Byte-identical body, `X-Idempotent-Replay: true` on 2nd; only ONE consent row and ONE audit row appended | Byte match; header present; DB shows exactly 1 row / 1 audit row | PASS |
| 10 | Idempotency different key = new side effect | Third `POST` with different key | New consent row + new audit row | Exactly 2 total | PASS |
| 11 | Sealed serializer (owner) | `GET /api/v1/users/me/claims` | `work_auth.value` = real object | `{status: unspecified, note: ...}`, sensitivity=sealed | PASS |
| 12 | Sealed serializer (admin non-owner) | `GET /api/v1/users/{user_zero_id}` as admin | value masked `•••• (sealed)`, `_sealed:true` | Masked as expected | PASS |
| 13 | Sealed serializer (support non-owner) | Same as admin | Masked | Masked | PASS |
| 14 | Role gating | `GET /api/v1/admin/feature-flags` as user / admin / support | 403 / 200 / 200 | 403 / 200 / 200 | PASS |
| 15 | Seed counts | Startup log + collection counts | taxonomy=13, companies=26 (25 real + SampleCo), sample_jobs=15 (is_sample=true), feature_flags=4, admin_users=2, User Zero id populated | Exact match | PASS |
| 16 | External ingress full-stack | Same suite hit against preview URL | Everything works through `/api/*` ingress | All 200/403/expected | PASS |

### Endpoints delivered

- `GET  /api/health`
- `GET  /api/v1/meta/policy`
- `POST /api/v1/auth/signup`
- `POST /api/v1/auth/login`
- `GET  /api/v1/auth/me`
- `GET  /api/v1/consents`
- `GET  /api/v1/consents/scopes`
- `POST /api/v1/consents`
- `GET  /api/v1/users/me`
- `PATCH /api/v1/users/me`
- `POST /api/v1/users/me/change-password`
- `GET  /api/v1/users/me/claims`
- `GET  /api/v1/users/{user_id}` (admin/support)
- `GET  /api/v1/admin/feature-flags` (admin/support)
- `GET  /api/v1/admin/health` (admin/support)
- `GET  /api/v1/passport/ping` (consent-gated on `process_career_data`)

### Mongo collections + indexes bootstrapped

`users` (email unique), `consent_records` ((user_id,scope,ts)), `authorization_scopes`, `audit_logs`, `feature_flags` (key unique), `admin_users` (user_id unique), `documents` (user_id, sha256), `claims` ((user_id,type)), `taxonomy` (family unique), `companies` (domain unique), `jobs` (canonical_key unique + status + taxonomy_family), `idempotency_records` (key unique + TTL 7d).

### Known deviations / explicit stubs

- Auth: internal JWT+bcrypt (docs originally specified Clerk). Isolated in `domains/auth/*` — swappable.
- Storage: `LocalDiskStorage` under `/app/backend/storage` behind an S3-compatible interface. `documents` rows still carry `s3_key + sha256`.
- Email / analytics / error-tracking: **LABELED INTERNAL STUBS** in `services/{email_stub,analytics_stub,error_tracking_stub}.py`. They log only. Interfaces preserved.
- LLM: not used in Phase 1. `EMERGENT_LLM_KEY` confirmed available. Wiring lands in Phase 4.
- Billing (Stripe): deferred to Phase 6.

### Backend testing agent handoff

Please verify all 16 rows above and stress-test:
1. Signup + login + me with a fresh email.
2. Consent grant/revoke/re-grant cycle for a non-required scope and for `process_career_data`.
3. Idempotency replay (same key returns identical body; audit rows do NOT duplicate).
4. Role gating (user → 403 on admin routes; admin/support → 200).
5. Sealed masking for admin/support vs the owner.
6. Seed counts (13 taxonomy, 26 companies, 15 sample jobs is_sample=true, User Zero with claims all user_approved=false).

Credentials in `/app/memory/test_credentials.md`.

## Frontend Tests
_(populated only after user approves frontend testing)_

## Agent Communication

- agent: "testing"
  message: |
    Ran /app/backend_test.py against the external preview URL
    (https://af7cc636-8506-4548-af82-a1a50aae0158.preview.emergentagent.com)
    plus direct MongoDB reads (mongodb://localhost:27017, db=opportunityos)
    for seed-integrity and ledger assertions.

    38 named sub-checks executed. ALL 38 PASS. Coverage matches the 13
    numbered items in the Phase-1 review request:

      1. GET /api/health → 200 mongo:true ✅
      2. /api/openapi.json exposes all 13 required paths ✅
      3. Signup happy path (only process_career_data:true) → 201 with token+user ✅
      4. Signup with process_career_data omitted → 400
         detail={error:"required_consent_missing", scope:"process_career_data"} ✅
      5. Login for user/admin/support returns access_token with correct roles ✅
      6. /auth/me echoes correct role for all three tokens ✅
      7. Consent gate: ping 200 → revoke 201 → ping 403 (machine-readable body)
         → re-grant 201 → ping 200 → consent_records ≥3 rows on process_career_data ✅
      8. Idempotency:
         a. Same Idempotency-Key: byte-identical bodies, second has X-Idempotent-Replay:true ✅
         b. Exactly ONE consent_records row + ONE audit_logs row per idempotent pair ✅
         c. Different Idempotency-Key + same body → new consent row + new audit row ✅
      9. Sealed serializer:
         a. Owner (User Zero) sees {status:"unspecified", ...} + sensitivity:"sealed", no _sealed flag ✅
         b. Admin sees value:"•••• (sealed)" with _sealed:true ✅
         c. Support sees identical masking ✅
     10. Role gating: user 403, admin 200, support 200; flags contain
         feed_enabled:true, ai_generation_enabled:false,
         application_tracker_enabled:false, billing_enabled:false ✅
     11. Seed integrity (verified by direct DB reads):
         a. taxonomy=13, all 13 families from /app/backend/domains/seeds/data.py present ✅
         b. companies=26; SampleCo verified_domain:false; 25 real have verified_domain:true and green_lane:false ✅
         c. jobs where is_sample=true count=15, all canonical_key sampleco.demo::sample-NN unique ✅
         d. User Zero: 16 claims total, ALL user_approved=false and verification.level=0; work_auth sensitivity:"sealed" ✅
         e. feature_flags contains exactly the 4 expected keys ✅
         f. admin_users has admin@ role=admin and support@ role=support ✅
     12. Users domain:
         a. PATCH /users/me updates name + writes exactly one user.profile_update audit row ✅
         b. change-password: wrong current → 400 current_password_incorrect ✅
                            correct current → 204 ✅
                            login with new password works ✅
                            reverted User Zero password back to Passport!Test0 ✅
                            login with seed password works after revert ✅
     13. Concurrency sanity: fired two idempotent POSTs concurrently against
         email_me → both 201, exactly ONE consent_records row appended ✅

    No deviations from spec detected. Nothing is mocked in this suite —
    all checks hit the real ingress and real MongoDB. Test credentials in
    /app/memory/test_credentials.md remain valid (User Zero password reverted
    to Passport!Test0 at end of run 12).

    Recommendation: main agent can summarise and finish Phase 1 backend.

