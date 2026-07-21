# OpportunityOS — Product Requirements (living)

**Codename in repo:** LYNK.
**Web-first.** Backend: FastAPI @ 8001. Frontend: React @ 3000. DB: MongoDB. Ingress: all backend under `/api/*`.

---

## 🚧 Founder integrations mandate — in progress

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

**All eight founder integration milestones (A → H) DONE.** Only P2
behaviour-neutral visual polish remains (Milestone I, deferred until final
QA).

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

