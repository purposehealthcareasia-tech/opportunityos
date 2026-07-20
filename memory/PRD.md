# OpportunityOS — Product Requirements (living)

**Codename in repo:** LYNK.
**Web-first.** Backend: FastAPI @ 8001. Frontend: React @ 3000. DB: MongoDB. Ingress: all backend under `/api/*`.

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
Claims with `sensitivity="sealed"` serialize as `"•••• (sealed)"` for anyone who is not the owning user — including admin and support.

## Phase roadmap
- **Phase 1 (shipped):** Foundation — auth, consent ledger, audit, idempotency, sealed serializer, seeds, gated admin route.
- **Phase 2 (shipped):** Career Passport ingestion & approval flow — resume upload, real LLM parse (gpt-5, fallback gpt-4o), claim lifecycle (approve/reject/edit with `superseded_by`), preferences, eligibility (sealed) + gate engine v0 + coverage preview.
- **Phase 3 (this build):** 14-gate engine, weighted 0-100 scoring, jobs feed, link import (blocks LinkedIn/Indeed/Handshake), applications tracker with atomic state transitions, usage meters, submission-receipts contract (empty; index proven), LLM cost ledger, golden-set harness.
- Phase 4: Grounded AI generation (claude-sonnet-4 for tailoring + validator).
- Phase 5: Application submit path, tracker analytics, submission_receipts activation.
- Phase 6: Admin console + Stripe billing.

## Integrations
- **LLM:** `EMERGENT_LLM_KEY` via `emergentintegrations`. Resume parsing pinned to primary `gpt-5` w/ fallback `gpt-4o`. Actual model string persists on every parsed claim's `source.model` and on `documents.parse_meta.model_used`. Every call appends to `llm_costs` (task, model, tokens_in/out, cost_usd_est, price_source, ts).
- **Storage:** local disk at `/app/backend/storage` behind an S3-compatible interface.
- **Email / analytics / error tracking:** internal stubs.
- **Background queue:** `services/queue_stub.py` (asyncio semaphore).
- **Anti-virus:** `av_status="skipped_v0.1"` on every uploaded document.
- **Billing:** deferred to Phase 6.
- **Internal ingest:** `POST /api/internal/jobs/bulk` guarded by `INTERNAL_SERVICE_TOKEN` header (missing→401, wrong→403, not-configured→503; token never appears in logs/bodies).

## Deviations of record
- Auth: internal JWT+bcrypt (docs originally specified Clerk). Isolated in `domains/auth/*` — swappable.
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
