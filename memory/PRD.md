# Fynd — Product Requirements Document

## 🚀 Phase 6 Batch D UI (2026-08-12) — /onboarding/launch React screen — READY FOR GATE

**Immediate task closeout.** The founder-blocking Phase 6 UI gap is CLOSED. `/onboarding/launch` React screen is landed, wired, screenshot-covered, and pytest-regression-checked. **Awaiting founder-run split tester brief for gate PASS.**

- **Landed:** `/app/frontend/src/pages/OnboardingLaunch.jsx` (single page composing Attest → Spectrum → Wave preview → Verbatim consent → Authorize).
- **Wired:** `App.js` (protected route `/onboarding/launch`) + `Sidebar.jsx` (**Launch** entry, Rocket icon).
- **Rails held:** consent language rendered VERBATIM per scope from `/meta/policy` (no collapsing); `pay_floor: null` → honest "no verified pay history yet" card (never fabricated); Authorize disabled when any required scope unchecked; empty / error / 402 / success all render with distinct data-testids.
- **Fixture users** (seeder deterministic on every backend startup, documented in `test_credentials.md`):
  - `fixture-ead@opportunityos.dev / Fixture!Test1` — 50 credits (LAUNCH-READY happy path; 4 seeded apps for real-debit path)
  - `fixture-broad@opportunityos.dev / Fixture!Broad1` — 0 credits + 1 shortlisted app marked `fixture_purpose=phase6_batch_d_402_demo` (direct HTTP 402 `paused_no_credits` exercise on `POST /api/v1/email-route/dispatch`)
- **Direct 402 exercise verified (2026-08-12):** `POST /api/v1/email-route/dispatch` for `fixture-broad@` returns HTTP 402 `{state:"paused_no_credits", balance:0, error:"insufficient_credits"}` deterministically. Discovery: `GET /api/v1/applications` → single row for this fixture.
- **Screenshots** (6 states) under `/app/docs/phase-6-screenshots/`: `launch_loading.jpeg · launch_ready.jpeg · launch_paused_no_credits.jpeg · launch_consent_and_402_footer.jpeg · launch_missing_consents.jpeg · launch_success.jpeg`.
- **Regression pytest (2026-08-12, post-seed):** `37 passed in 1.37s` on the 6 Phase 6 test files. Zero regressions.
- **openapi.json** healthy at 205 paths including `/api/v1/onboarding/launch, /api/v1/credits/me, /api/v1/spectrum/suggest, /api/v1/claims/attest-all`.
- **Evidence appended** to `/app/docs/PHASE-6-EVIDENCE.md` §UI with full state-coverage table and verbatim-consent smoke.

**Next after founder gate PASS:** resume Tier-2 code-review burn-down (Admin.jsx `IntegrationsTab` split + 51 nested-ternary resolution).

---

## 🏁 Sequence status (2026-08-10 CLOSEOUT · WEBSITE MACHINE PHASES 0-5 COMPLETE · local `main` HEAD `0e0b38a5`)

**PHASE 0-5 SEQUENCE COMPLETE. FOUNDER GATE-PASSED 8/8. MERGE COMPLETE LOCALLY. AWAITING FOUNDER SAVE-TO-GITHUB + PUBLISH.**

| Phase | Codename | Verdict | Date | Evidence |
|---|---|---|---|---|
| 0 | Fynd Liquid retheme + rebrand | **PASSED** | 2026-08-04 | `docs/PHASE-0-EVIDENCE.md` |
| 1 | CONVERSION LAYER | **PASSED** (founder tester-leg) | 2026-08-06 | `docs/PHASE-1-EVIDENCE.md` |
| 2 | INTELLIGENCE VISIBLE | **PASSED** (founder tester-leg) | 2026-08-08 | `docs/PHASE-2-EVIDENCE.md` §6 |
| 3 | SUPPLY ENGINE | **PASSED** (founder tester-leg + abuse-log persistence lock) | 2026-08-08 | `docs/PHASE-3-EVIDENCE.md` §6 |
| 4 | ELIGIBILITY ENGINE & EXPORTS | **PASSED** (founder tester-leg + null-envelope uniformity lock) | 2026-08-08 | `docs/PHASE-4-EVIDENCE.md` §5-§6 |
| 5 | WEBSITE SCALING TIER (5a-5j) | **PASSED** (founder 8/8 briefs · D1 D2 D3 · Gate A + Gate B + Gate C) | 2026-08-10 | `docs/PHASE-5-EVIDENCE.md` §Gate C addendum |

**Founder final verdict at HEAD `22941607` (2026-08-10):** PASS on 8/8 briefs.
- D1 — interview-prep grounded generation (3 questions, PRACTICE label, `grounded:true`, every answer citing verified approved claim, firewall 3 kept / 0 dropped; project category honestly empty) ✓
- D2 — employer dashboard member path own-data-only with `cross_employer_disclosure:false` + non-member 403 ✓
- D3 — extension fully compliant (MV3, `[activeTab,storage]` only, empty `host_permissions`, ZERO page-content APIs by grep, blocklist enforced before any network call, single validated `/employers/connect` target, 6/hr client cap) ✓

**Phase 5 Gate C burn-down (this session, all shipped at HEAD `0e0b38a5`):**
- FIX 1 — claims schema drift (`state/kind` → `status/type`) locked structurally in `domains/claims/schema.py` (SSoT). 3 anti-drift tests.
- FIX 1B — second-layer sub-drift (`data` → `value` + per-type value keys `institution`/`role`/`start`/`end`) surfaced during evidence capture via observed-over-remembered rail. Extended `schema.py` with `FIELD_VALUE`, `claim_value()`, per-type key maps, `_year_from_iso_month()`. **PUBLIC API surface unchanged** — only the source was rewired. Anti-drift guard extended to catch raw `"data":` literals.
- FIX 2 — `interview_receipts` verify_endpoint URL corrected (`ghosting-evidence/verify`).
- FIX 3 — `employer_memberships` fixture (`fixture-employer-member@` / `Fixture!Emp1`) rebaselined on startup for the 5g member-path E2E.

**Merge packet:** `docs/MERGE-PACKET.md` §9 (Phase 5 Gate closeout, packet SHA `22941607` → final SHA `0e0b38a5`).
- Dry-run: **CLEAN** (no conflicts, fast-forward feasible on push).
- Tripwire: **CLEAN** (`backend/.env` + `memory/test_credentials.md` both untracked, verified via `git ls-files`).
- Local merge: **COMPLETE** — main is a strict fast-forward (140 commits ahead of `origin/main` at merge-base `35032790`).
- Push: **BLOCKED** on GitHub connection auth (`fatal: could not read Username for 'https://github.com'` · exit 128) — expected external blocker, cleared by founder's Save-to-GitHub click.
- Publish click: founder's physical action.

**Suite state at final SHA `0e0b38a5`:**
- Focused Phase-3/4/5 subset: **191 passed / 0 skipped** (+27 over pre-Gate-C `164p/3s`, 0 Gate-C regressions).
- Full pytest at `CI_TEST_ISSUER_ENABLED=true` (documented preview state per `test_credentials.md` line 11): **633 passed / 30 failed / 3 skipped in 5:36.**
- The 30 failures are all fixture-state-pollution live-integration tests (git-stash-verified as pre-existing at both `ba4008c7` and `78eec143`). Filed as **P2 fixture-cleanup** in the residual backlog. Table in `docs/MERGE-PACKET.md` §9.4.
- Skipped 3 are motor/pytest-asyncio incompatibility, locked by live-curl evidence — NOT feature gaps.

---

## 🌊 Phase 5 — WEBSITE SCALING TIER — LANDED 2026-08-09 · GATE-PASSED 2026-08-10 (evidence: `/app/docs/PHASE-5-EVIDENCE.md`)

**Feature deltas (10 items):** 5a Passport Share Link · 5b Materials A/B · 5c Extension Capture-Anywhere (MV3 minimal) · 5d Interview Prep Grounded · 5e Responds-Fast Badge · 5f Interview Receipts · 5g Employer Dashboard · 5h Layoff-Day Mode · 5i Passport-as-API v1 · 5j Cohort Intelligence.

**Spec-only carry-forwards** (build nothing this pass, per founder brief): `PHASE-5-SPECS/{VELOCITY-BRIDGE, WARM-INTRO-FINDER, NEGOTIATION-COPILOT, BACKGROUND-PRE-CLEARANCE, A2A-PROTOCOL}.md`.

**New domains:** `share`, `materials_ab`, `interview_prep`, `badges`, `interview_receipts`, `employer_dashboard`, `layoff_day`, `passport_api`, `cohort_intel`.
**New extension surface:** `/app/extension/` (MV3, `[activeTab, storage]` only, empty `host_permissions`, no content scripts, no scraping, no CAPTCHA interaction).
**New consent scopes:** `share_passport`, `interview_prep_generate`, `passport_api_access`.
**New SSoT accessor module:** `backend/domains/claims/schema.py` — every consumer of `db.claims.*` now imports from here.
**Anti-drift guards:** `tests/test_claims_schema_no_drift_guard.py` + `tests/test_consent_scope_enum_guard.py`.

**Rails absolute across all 10 items** — verified in `PHASE-5-EVIDENCE.md` §Rails: consent gates on every new surface, caps never bypassed, dry-run email dispatch, no scraping (5c manifest `host_permissions: []`), no CAPTCHA interaction, follow-ups never auto-sent, honest empty states, user-scoped only, cross-employer disclosure `false` on every 5g response, single verify endpoint, single signing key.

---

## 🔧 Post-Phase-5 residual backlog (P2, decide-and-document)

**Filed 2026-08-10 after gate PASS. To be worked opportunistically after Save-to-GitHub + Publish.**

### P2a — Live-integration fixture-state cleanup (30 tests)
Pre-existing (git-stash-verified) test failures in `test_phase*_e2e`, `test_fixture_acceptance_b`, `test_phase*_integration_live`, `test_round2_*`, `test_receipts_immutability`. Root cause: preview DB accumulates `applications` / `application_outcomes` / `match_scores` rows across repeated pytest sessions; `_rebase_fixture_user()` fires only on backend startup, not between individual test cases. Full table in `docs/MERGE-PACKET.md` §9.4.
**Options (decide-and-document):** (a) per-test rebase fixture with `@pytest.fixture(autouse=True)` scoped to `test_*_e2e` files; (b) mark these tests `@pytest.mark.live_integration` and split them into a separate pytest run that begins with a rebase call; (c) leave as-is and treat the 191p focused subset as the regression gate.

### P2b — Tier 2 code-review refactors
Listed in `docs/CODE-REVIEW-REMEDIATION.md`: function-complexity refactors, 4 component splits, 51 nested ternaries. All Tier 1 items already shipped (MD5→SHA-256, seeder secret parameterization, frontend stable keys, useMemo additions).

### P2c — Missing root data-testids
`/eligibility` and `/passport` pages are missing root `data-testid` anchors. Cosmetic testability gap — filed in `docs/CODE-REVIEW-REMEDIATION.md`.

### P2d — Dedicated ElevenLabs test suite
Honest gap called out in the 16-integration audit — no dedicated `test_milestone_j_voice.py`. Registry-level coverage only. Not blocking `CONFIGURATION_REQUIRED` status truthfulness.

---

## 🏁 Original Phase 0-4 sequence status (pre-Phase-5, retained for history)

| Phase | Codename | Verdict | Date | Evidence |
|---|---|---|---|---|
| 0 | Fynd Liquid retheme + rebrand | **PASSED** | 2026-08-04 | `docs/PHASE-0-EVIDENCE.md` |
| 1 | CONVERSION LAYER | **PASSED** (founder tester-leg) | 2026-08-06 | `docs/PHASE-1-EVIDENCE.md` |
| 2 | INTELLIGENCE VISIBLE | **PASSED** (founder tester-leg) | 2026-08-08 | `docs/PHASE-2-EVIDENCE.md` §6 |
| 3 | SUPPLY ENGINE | **PASSED** (founder tester-leg + abuse-log persistence lock) | 2026-08-08 | `docs/PHASE-3-EVIDENCE.md` §6 |
| 4 | ELIGIBILITY ENGINE & EXPORTS | **PASSED** (founder tester-leg + null-envelope uniformity lock) | 2026-08-08 | `docs/PHASE-4-EVIDENCE.md` §5-§6 |

**Founder independent tester-leg (2026-08-08) verdict on the 6 P0 fixes:** ALL PASS.
- test_credentials.md restored + untracked ✓
- Origin resolver: `unrecognized_host` for bogus / `verifiable_board`+`greenhouse`+`lucidmotors` for real ✓
- 429 fires + admin abuse-log route wired (403 as non-admin, by design) ✓
- Eligibility knowns carry `{value, source, as_of}` per datum ✓
- `?format=pdf` returns explicit 501 `pdf_not_available` with `formats_supported`/`formats_planned` ✓
- Signature verify: true on intact / false on tampered manifest ✓

**2026-08-08 closeout items (shipped):**
- Cosmetic uniformity: `opt_end`/`earliest_start`/`sealed_at` now wear the `{value, source, as_of}` envelope even when null. Consumers can iterate `known.items()` with a single shape assumption. 2 new anti-regression tests.
- Abuse-log persistence lock: end-to-end write-then-read test proves the 429 row lands in `supply_abuse_log` AND is queryable via `GET /api/v1/admin/supply/abuse-log` with the exact documented shape. 1 new anti-regression test.

Pytest at closeout SHA `b87d9c14`: **114 passed / 3 skipped** (Phase 1 baseline 72p/3s → **+42 pass cumulative, 0 regressions**).

The 3 skipped tests are motor/pytest-asyncio incompatibility skips, locked by live-curl evidence in `PHASE-1-EVIDENCE.md` §v and §vii. They are NOT feature gaps.

---

ements (living)

**Codename in repo:** LYNK.
**Web-first.** Backend: FastAPI @ 8001. Frontend: React @ 3000. DB: MongoDB. Ingress: all backend under `/api/*`.

---

## 🌊 Phase 1 — CONVERSION LAYER — LANDED 2026-08-06 (evidence: `/app/docs/PHASE-1-EVIDENCE.md`)

**Gate close-out (2026-08-06T~23:47Z):**
- **G3d (Data Integrity)** — CLOSED. Root-cause CLASS: schema drift.
  `_snapshot_consents` was addressing legacy field names never present in
  the Phase-6-hardened `consent_records` shape (correct: `granted: bool`
  + `ts`). Blast radius: **6 wave_authorizations rows** with empty
  `consents_snapshot={}`, all belonging to `fixture-ead@opportunityos.dev`
  (0 real users; preview has none); split evenly across both wave paths
  (**3 × user_batch + 3 × standing_wave_aab_tick** — both were affected).
  Would have shipped absent the gate. Fix + immutable annotation trail
  (`consents_snapshot_correction` sub-document per row, never a silent
  rewrite of the original) + dual-path regression test
  (`tests/test_phase1_wave_consent_snapshot.py` — 4 passed) +
  annotation invariance tests
  (`tests/test_phase1_g3d_annotation_trail.py` — 3 passed).
- **G1d (Data Gap)** — CLOSED. Seeded second SAMPLE employer
  `ResponsiveDemo (fixture)` with 3 response outcomes (median 4.0d, 3/3
  responded); `sort=speed` now differentially ranks it at positions
  [0,1] above SampleCo [2..10] with the honest `"no response data yet"`
  label on the tail bucket. Verified via curl + Playwright.
- **G7-G10 (Frontend leg)** — CLOSED. Self-contained Playwright script
  `/app/docs/phase-1-screenshots/g7_g10_evidence.py` executes headless
  Chromium as fixture-ead@, drives all four surfaces, writes structured
  JSON + screenshots. `all_passed=true`. UI-login used (survives
  dev-mode 502s + hot-reload restarts via `_goto_stable` retry + 3-tier
  login retry).
- **Focused pytest**: **79 passed / 3 skipped** (baseline 72p/3s → **+7 pass,
  0 regressions**). Skipped tests unchanged, each locked by live curl
  evidence.

Shipped in one atomic-reload cycle under the "Precision Protocol" (evidence gates, measured baselines, no zero-regression claims without proof):

**§i — Backend rebrand ("OpportunityOS" → "Fynd")** — user-facing strings only across 8 backend files (server title/log, LLM system prompts, tool UA strings, seed admin/support display names, EEO consent copy, 4 policy scope descriptions). Dev-facing comments/docstrings retained by design. Frontend fallback `consentScopes.js` updated to note the backend rebrand is complete; helper stays as a defensive floor.

**§ii — Scorer unfreeze** — new `services/scored_cache.py` (bounded LRU, key = `(ctx_sig, job_id, job.last_verified_iso, weights_version)`) memoizes `gate_engine.evaluate() + scoring.score()` per user × job so the 22k-job scoring loop is off the `/feed` hot path. **Byte-identical proven** over the stable pre/post intersection (`pre_stable_md5 = post_stable_md5 = acd2f89b7af6cb3041d1e005dd8c3a81`; 9 passing + 22,440 excluded jobs match exactly). Weights/gate/scoring code untouched — same functions run on miss; hit returns exact stored tuple. Byte-identity was the founder-mandated gate — passed.

**§iii — Feed LCP re-measure** — `backend/tools/feed_lcp_probe.py` Playwright headless, 3 runs against preview `/feed` as `fixture-ead@`. **LCP median 692 ms · min 636 ms · max 740 ms** (Phase 0 closeout was 3.98 s). Dev-mode caveat cited (`react-scripts start` + `uvicorn --reload`).

**§iv — 1a Speed-ranked feed sort** — additive `sort=speed` on `GET /api/v1/jobs/feed`. Rank key = `(has_data ∈ {0,1}, median_days_to_response ↑, -score)`. Data source: THIS USER's own `application_outcomes.compute_group_stats(group_by=employer, since_days=90)` — user-scoped, no cross-employer response-history sharing (privacy hard-stop preserved). No-data employers sink to end, labeled `"no response data yet"`. Default sort unchanged (`best_fit`).

**§v — 1b Apply Wave + Spectrum Builder** — new `POST /api/v1/wave/authorize` batch-queues eligible spectrum jobs into Submit Sprint. Cap NEVER bypassed (rolling 30-day per-employer cap counts wave-queued rows against remaining slots). Consent-scope snapshot recorded on every `wave_authorizations` row. **`GET /api/v1/wave/preview`** returns the exact dry-run breakdown + eligible_job_ids the wave WOULD queue, read-only, same consent gate. Standing Wave scope persisted to `standing_waves`; **wired into `discovery.refresh_all`** so new arrivals auto-queue matches on every refresh cycle, cap enforced identically (`services/wave.run_standing_waves_after_aab_tick`).

**§vi — 1c Instant-scheduling link** — new persisted `booking_url` field on `PreferencesPayload` (https:// validated). If set, appended verbatim to outbound email body after preflight passes ("Book a time: <url>"). Never invents placement. Outbox row records `booking_url_attached: true`.

**§vii — 1d Follow-up drafts** — new `follow_up_drafts` collection + endpoints (`POST /follow-ups`, `GET /follow-ups`, `POST /follow-ups/{id}/approve`, `POST /follow-ups/{id}/discard`). Schedules from user's own employer median-days-to-response (fallback 7d). **HARD INVARIANT (test-locked):** `test_no_dispatch_sweep_touches_drafts` static-grep test fails if any code path outside the follow-ups module writes to `follow_up_drafts`. Approve is the ONLY transition-to-send — creates a FRESH `email_outbox` row via existing `email_route.dispatch` pipeline (still dry-run in preview).

**Fixed side quest — pre-existing 500 bug in `server.py::scrub_validation_error`** — pydantic v2 stuffs raw `ValueError` into `err["ctx"]["error"]` which broke `json.dumps`. Handler now coerces `ctx` values to strings, so all custom field validators return clean 422s.

**Pytest baseline: 62 → 72 passed / 3 skipped / 0 regressions** (skipped tests locked by live curl evidence). Same ordered command as Phase 0 §14.1 + 3 new Phase-1 test files.

**Frontend surfaces landed (E2E on Fynd Liquid, `fixture-ead@` verified via Playwright):**
- Sort=speed toggle in `Feed.jsx` with `SpeedChip` component; honest empty-state label `"no response data yet"` verified (9 chips visible for fixture-ead@).
- `ApplyWaveCapsule.jsx` — collapsible capsule → `GET /wave/preview` on open → renders breakdown + eligible list → confirm button DISABLED until preview loads AND eligible_count > 0 → Standing Wave toggle → success/consent-revoked/error states.
- `Preferences.jsx` — new `booking_url` row with https validation feedback; server 422 with `loc.includes('booking_url')` surfaces the honest server message inline.
- `FollowUps.jsx` at `/follow-ups` — draft list with filter tabs, per-draft body preview + median-source label, explicit approve dialog (destination + subject required) that creates a FRESH email_outbox row via `email_route.dispatch` (dry-run), discard is idempotent. Sidebar link added.

**Production-build Lighthouse one-off:** CRA `yarn build` → `npx serve -s build -l 4173`, measured LCP median **276 ms** (bundle: 276K JS + 52K CSS), then torn down. Dev-mode LCP median **692 ms**. Reported side-by-side with x-origin cookie caveat — never extrapolated.

**Rails held all pass**: preview only, no merge/push/deploy, no real submissions, no scraping, ONE supervisor restart never needed (uvicorn hot-reload picked up all changes atomically), byte-identical scoring proof committed BEFORE Step (iii), cap NEVER bypassed, follow-up drafts unreachable by any dispatch sweep.

---

## 🌊 Phase 0 — Fynd Liquid retheme + rebrand — PASSED 2026-08-04

**Rebrand:** OpportunityOS → **Fynd** (user-visible strings only — code identifiers, env vars, DB name, and API paths unchanged).

**Branch:** `feat/liquid-ui` @ HEAD `daf06b68…` (+ two sanctioned commits on top of `1f6009fc`). Founder confirmed rebase is NOT required (2026-08-04).

**Shipped in Phase 0 (working tree on top of `1f6009fc`):**
* Fynd Liquid design tokens (`src/index.css` + `tailwind.config.js`): 3 glass elevations (`liquid-bar / liquid-card / liquid-sheet`), specular top-edge, concentric radii, dark-first base `#0B0D10`, warm calm radial haze.
* Guardrails: `prefers-reduced-transparency: reduce` drops backdrop-filters to solid tints; `prefers-reduced-motion: reduce` collapses transitions to 0.001 ms.
* 8 screens rethemed (Landing / Login / Feed / Applications / Outcomes / Passport / Submit-Sprint / mobile-390 sweep). Screenshots in `/app/docs/phase-0-screenshots/`.
* New components: `FyndMark`, `SmartCTA`, `DailyBudgetCapsule`, `StreakChip`, `SurpriseMeCapsule`.
* Backend Surprise Me: `POST /api/v1/jobs/surprise-me` + `GET /api/v1/jobs/surprise-me/status`. Consent-gated on `discover_jobs`; 5/day limit; only real, non-sample, out-of-lane-eligible jobs; verbatim `why_you_qualify` from `reason_codes[].explanation` + gate `notes[]`.
* `_rebase_fixture_broad_user()` in seeder — wider-prefs fixture user (`fixture-broad@opportunityos.dev` / `Fixture!Broad1`) with `status=us_citizen`, no `role_families` filter, `salary_floor=0`. Enables the real Surprise Me draw path against Greenhouse / Lever / Ashby corpus.
* `application_outcomes` / `budget_reallocations` / `kill_list` / `self_healing_events` / `preflight_verdicts` collections are wiped/reseeded on every backend restart alongside fixture users.
* Apply-at-Birth scheduler activated behind `APPLY_AT_BIRTH_ENABLED=true` env flag (founder-authorized).
* Field-Structure Capture pass on 20 ATS URLs — zero PII leaks (form_maps DB scan clean).

**Phase 0 burn-down (2026-08-04, closeout):**
* 390 px `DailyBudgetCapsule` overlap on `/outcomes` — **FIXED** (Layout `pb-24` → `pb-32` on mobile). Post-fix 390 px screenshot recorded.
* Surprise Me 403 consent-revoked path — **VERIFIED** live (curl trace in `/app/docs/PHASE-0-EVIDENCE.md` §8:4).
* Surprise Me real draw against real corpus — **VERIFIED** via `fixture-broad@` (returned live PsiQuantum row, `is_sample=false`).
* Interview-scheduled micro-delight — **DEFERRED** (Phase 1 scope).
* Presentation-only perf pass (frontend-only): `<link rel="preconnect">` + `<link rel="dns-prefetch">` to `%REACT_APP_BACKEND_URL%` — Landing Lighthouse 68 → **80** (LCP 5.4 s → 4.1 s). Feed Playwright LCP 5.4 s → 3.98 s. Named limitation: preview runs `react-scripts start` (dev mode), which caps LH scores ~20–30 points below production builds. Scorer-unfreeze deferred until AAB 24 h window closes.
* Focused pytest baseline at closeout: **62 passed / 0 failed** (matches pre-closeout count).

**24 h AAB observation window:** RUNNING as of 2026-08-04 evening. Backend has NOT been restarted since window start. Median posting→queue metric + any 429/5xx events will be reported when window closes.

**NOT-VERIFIED (open items for tester or later burn-down):**
Guardrails empirically (reduced-transparency / reduced-motion / WCAG contrast), SmartCTA rungs 1–2, DailyBudget cap-reached state, StreakChip visible state, `liquidRipple` wiring, sidebar 768–1023 px breakpoint, dark-mode fresh-boot audit, some rethemed screens at pixel level. Full list in `/app/docs/PHASE-0-EVIDENCE.md` §8.

**Rails held all pass:** preview only, no merge/push/deploy, no `.env` edits, no employer submissions, no scraping/CAPTCHA-bypass, no backend restart during AAB window.

**Awaiting:** independent tester pass on the 3 Fynd Liquid user flows (Surprise Me — incl. 403 + real draw via `fixture-broad@` · assisted-lane chip on Applications · kill-list Restore on Outcomes) plus zero-regression shortlist→sprint→simulate spot-check.

**Post-Phase-0 (do NOT start until founder signals Phase 0 PASS):**
* Phase 1 CONVERSION LAYER: speed-ranked feed sort · Apply Wave + Spectrum Builder · instant-scheduling link · follow-up engine.
* Phase 2 INTELLIGENCE VISIBLE: `/outcomes` sparklines · weekly digest · rejection autopsy.
* Phase 3 SUPPLY ENGINE: `/employers/connect` · request-this-employer voting.

---


## 🎯 Merge-decision packet (2026-07-28 · final)

Branch `feat/real-job-discovery` @ **HEAD `1f6009fcfea618bafa82f9228c1cb63a499a4fb2`**. Discovery + precision-autopilot lane is **feature-complete and verified in preview**.

**Tester verdicts to date:**
* Phase 3 (14-gate + feed): PASS (51/51) — `/app/test_reports/iteration_20.json`.
* Phase 4 low-supply prompt: PASS.
* Phase 4 email-route + receipt collision fix: PASS.
* Phase 4 · Item 4 fill-and-abort 20/20: PASS.
* Phase 5.0 pre-flight validator: PASS (3/3).
* Phase 5.1 lifecycle truthfulness: PASS.
* Phase 5.1 preflight simulate: PASS. Docs aligned on 401-vs-403 auth-failure semantics.
* Phase 5.2 form-map cache hygiene: PASS (20 docs, `structure_captured=false`, PII scan null).
* Phase 5.3/5.4 outcome + self-healing evidence: PASS.
* Additive backend surface (kill-list list/restore + reallocation/latest): PASS (7/7 endpoint tests + live curl).
* Three P2 UI surfaces (simulate feedback / assisted-lane chip / kill-list restore): **4/4 PASS** by independent tester 2026-07-28 (`/app/test_reports/iteration_21.json`).

**Founder-gated (deliberately parked) pending explicit green-light:**
* Apply-at-birth polling scheduler wiring. Services + tiers shipped; scheduler task not attached.
* New sanctioned field-structure capture dry-run. Form-map cache wired only to the URL-fingerprint bootstrap from the already-approved 20/20 pass.

**Post-merge backlog (spec-only, do NOT build until founder green-lights post-merge work):**
* **Outcomes drift sparkline** — a per-employer week-over-week sparkline of `response_rate` and `median_days_to_response`, driven purely from the existing `application_outcomes` ledger. Read-only, no new write path. Strengthens the `/outcomes` explainer from "why fewer apps to X today" into "and here's the observed trend that led to it". Would sit on the existing `/outcomes` page above the reallocation panel; every data point is already produced by `outcome_autopilot.compute_group_stats(user_id, since_days=…)` today.

**Config-required (unset by design):** USAJOBS (`USAJOBS_API_KEY`, `USAJOBS_USER_AGENT_EMAIL`), live SMTP (`EMAIL_ROUTE_*`), Apple sign-in, Twilio Verify OTP, Resend / SendGrid webhooks, Razorpay / PayPal / Paystack, ElevenLabs, `PRIVATE_AUTOPILOT_OWNER_EMAILS`, and the production auth flip (`PROD_MODE=true` + `CI_TEST_ISSUER_ENABLED=false` + prod-only `CORS_ALLOW_ORIGINS` + rotated `JWT_SECRET / INTERNAL_SERVICE_TOKEN`). Full matrix in `/app/docs/DISCOVERY-EVIDENCE.md`.

**Rails (unchanged):** preview only, no merge, no push, no deploy, no `.env` edits, no real submissions, no live email, no scraping, no CAPTCHA bypass, no LinkedIn / Indeed / Handshake ingest, no new headless automation without founder green-light. All additive endpoints are consent-gated and read stored artifacts verbatim.

---

## 🚦 Phase 5 P2 close-out — SHIPPED (2026-07-28)

### Tester verdict (relayed 2026-07-28)
Phase 5.1–5.4 independent tester pass: **2 PASS · 2 EVIDENCE-INCOMPLETE · 0 FAIL**. Backend freeze **LIFTED**.
Three P2 UI surfaces subsequent tester pass: **4/4 PASS** (`/app/test_reports/iteration_21.json`).

### Fixture demonstration seeds (2026-07-28)
`backend/domains/seeds/seeder.py::_rebase_fixture_user` now also seeds ONE `state=assisted` application (pinned to a SampleCo `is_sample=True` job with `assisted_reason="FIXTURE seed · form-map fill confidence dropped below threshold (low_confidence · sample) — sanctioned demo row…"`) AND ONE active `kill_list` row (`employer="sampleco-demo-ghosts"`, `reason="FIXTURE seed · 5 silence outcomes and zero viewed/response/interview signals in the last 21 days · sanctioned demo row…"`). Both rows carry `fixture: true` in the payload and are wiped/reseeded on every backend restart. Feed acceptance geometry (9 passing / 6 excluded across the 15 SampleCo sample jobs on the fixture user) is preserved — feed reads `jobs`, not `applications`.

Wipe list extended to cover the Phase 5 per-user collections so successive rebases stay clean: `application_outcomes`, `budget_reallocations`, `kill_list`, `self_healing_events`, `preflight_verdicts`.


* **Test 1 lifecycle truthfulness** — PASS. Sweep metadata surfaced on `GET /api/v1/jobs/feed` (`discovery.{polled_at, sweep_id, boards_swept_last_pass, closed_last_pass}`). 75 closed jobs each carry `closed_detected_at`. Zero closed leak into live feed. 22,055 of 22,071 live rows stamped `last_polled_at`; the 16 unstamped rows are seed fixtures (not source-board rows).
* **Test 2 preflight simulate** — PASS. Auth + `submit_applications`-consent gated. Identity mismatch flagged with named `body_signature` finding. Zero writes to `preflight_verdicts`, `submission_receipts`, `email_outbox`. Application state untouched. **Unauth semantics correction (agent-side docs alignment 2026-07-28):** unauth returns **401** if the session cookie is missing and **403 csrf_check_failed** if the cookie is present but CSRF header is missing/mismatched. Both are correct; the earlier "unauth = 403" phrasing in the brief is now interpreted as "auth-layer rejects with 401 OR 403 depending on which layer trips first". Docstring at `backend/domains/preflight/__init__.py` amended to match.

### Tester close-out — done agent-side (2026-07-28)

**Test 3 · Form-map cache hygiene** — **PASS**. Collection: `form_maps` (not `form_map_cache`). Live inspection: **20 docs** (17 greenhouse + 3 lever) matches the sanctioned 20/20 dry-run pass. Every doc: `status=verified`, `structure_captured=false`, `fill_confidence=0.7`, `selector_map=[]`. PII scan across all 20 docs (fixture-user tokens `fixture-dryrun`, `opportunityos.dev`, `Fixture TestUser`, `555-0100`, plus `linkedin.com/in/fixture` etc., + forbidden keys `value/values/user_input/answer/answers/resume_text/name/email/phone/linkedin/filled_value/user_data/resume` inside selector_map entries, + regex sweep for any raw `local@domain.tld` in doc fields) → **null (clean)**.

**Test 4 · Outcome + self-healing** — **PASS**.
* `application_outcomes` — 1 fresh row inserted for the fixture app: `kind=response`, `days_to_response=3.0` computed by `compute_group_stats()` from a stamped `submitted_at`.
* `budget_reallocations` — 1 fresh row; allocations entry: `group=<employer_id>, weight=1.0, submitted=1, response_rate=1.0, reason="response_rate=100.00% on 1 apps · median_days_to_response=3.0"`. Zero rows have empty `reason`.
* `self_healing_events` — 1 fresh `map_demoted_low_confidence` row with `context={ats: greenhouse, fingerprint: url:f3110a4b1be7a34dfd757a5c, reason: "evidence: forced downgrade for tester close-out", previous_confidence: 0.7}`.
* `applications` — fixture app moved to `state=assisted` with `assisted_reason="evidence: forced assist for tester close-out"` and `assisted_at` timestamped. `services.self_healing.assisted_lane_reason(app_id)` returns the UI-ready dict verbatim.

### Additive backend surface (post-freeze)

Three read/mutate endpoints added on the existing `outcomes_router` (`backend/domains/outcomes/service.py`) — zero impact on sprint / email-route / validator / discovery paths.

| Method | Path                                              | Consent gate         | Behaviour                                                                                                   |
|--------|---------------------------------------------------|----------------------|-------------------------------------------------------------------------------------------------------------|
| GET    | `/api/v1/outcomes/kill-list`                      | `track_applications` | Returns `{active, recently_restored}` — active never null-elided; restored capped at last 10.               |
| POST   | `/api/v1/outcomes/kill-list/{employer}/restore`   | `track_applications` | Stamps `restored_at + restored_reason='user_restore'` on the existing row (append-only). 404 if not active. |
| GET    | `/api/v1/outcomes/reallocation/latest`            | `track_applications` | Returns the newest `budget_reallocations` row VERBATIM. No recompute (static invariant test locked).        |

Regression: `backend/tests/test_outcomes_endpoints.py` — **7 passed** (5 handler asserts + 1 static invariant that read endpoint never invokes `reallocate_daily_budget` and never writes `budget_reallocations` + 1 404 assertion). Focused Phase-5 suite total after this batch: **56 passed** (`test_outcomes_endpoints.py 7 + test_outcome_autopilot.py 5 + test_self_healing.py 7 + test_form_map_cache.py 8 + test_apply_at_birth.py 6 + test_preflight_validator.py 15 + test_receipt_compound_index_regression.py 5 + test_consent_scope_enum_guard.py 3`).

### P2 frontend surfaces

1. **Simulate inline feedback** — `frontend/src/pages/SubmitSprint.jsx`. Per-slot `Preview verdict` button dry-fires `POST /api/v1/preflight/simulate` with `{application_id, channel:'sprint_fixture', outbound_fields:null}`. Renders `Simulate: WILL PASS` (accent) or `Simulate: WILL BLOCK` (red) with the full `verdict.reasons[]` list, monospace, indented. Read-only contract respected: the sprint's local state is NOT promoted; the server writes nothing.
2. **Assisted-lane reason chip** — `frontend/src/pages/Applications.jsx`. Renders only when `app.state === 'assisted'`. Chip toggles a detail div that surfaces `app.assisted_reason` (verbatim) and `app.assisted_at`. `data-testid`s: `app-assisted-lane-chip-<id>`, `app-assisted-lane-detail-<id>`, `app-assisted-lane-reason-<id>`.
3. **Kill-list restore CTA + latest reallocation** — new `frontend/src/pages/Outcomes.jsx`, route `/outcomes`, sidebar link between Tracker and Analytics. Two panels:
   * `ReallocationPanel` — reads `/api/v1/outcomes/reallocation/latest`, renders each allocation with `weight`, `submitted`, `response_rate`, and the stored `reason` string verbatim inside a bordered explanation box.
   * `KillListPanel` — reads `/api/v1/outcomes/kill-list`; per-row `Restore` button hits `POST /api/v1/outcomes/kill-list/{employer}/restore`. On success the row moves into the `Recently restored` trail below, and a success flash banner appears.
   * Consent-blocked (403 `consent_required`) surfaces a friendly "grant `track_applications` under Settings" panel (`outcomes-consent-block`).

**Tester result on the three UI flows (`/app/test_reports/iteration_21.json`, 2026-07-28):** **100% (3/3 flows).** Simulate round-trip ~0.09s. Restore round-trip ~0.10s. Zero UI bugs / integration issues. One cosmetic note: reallocation group renders as its raw internal identifier (fixture data is `company_id` UUIDs) — mitigated with a small `formatGroupLabel()` helper that shortens UUIDs and picks the employer segment from `employer::role` canonical keys; the full string stays in the `title` tooltip and remains audit-truthful.

### Still parked (unchanged)
* Apply-at-birth scheduler wiring — founder-gated.
* New sanctioned field-structure capture dry-run — founder-gated.
* Employer-intake automation counts — permanently parked unless founder reverses.
* Workday tenant-path support — deferred until after merge decision.

---

## 🚦 Phase 5.1 → 5.4 batch — SHIPPED (2026-07-28)

### 5.0 Gap closure — sprint block-path functional test

`tests/test_preflight_validator.py::test_preflight_sprint_channel_blocks_on_unapproved_claim_reference` — corrupts a base resume line to reference an unapproved claim id; asserts `verdict.ok=False`, `reasons[0]=validator_blocked_mismatch`, `line_validation_failed:{n}` present, `block_and_route_to_review` moves the application to `state=review` with the correct `review_verdict_id`, and the verdict is persisted to `preflight_verdicts`. Passing.

### 5.1a Lifecycle sweep — truthfulness fix

`backend/services/lifecycle_sweep.py`: for each catalog board, compares fresh source IDs to `status='live'` DB rows and transitions absent rows to `status='closed'` with `closed_detected_at`, `closed_reason='absent_from_source_feed'`, `closed_from_status='live'`, plus stamps `last_polled_at` on every survived live row. Skips ambiguous responses (empty board OR fetch exception) so a transient failure NEVER produces a false close. Persists per-run audit to `lifecycle_sweep_runs`. Integrated into `discovery/service.py::refresh_all` — every refresh now includes staleness detection, and the summary carries a `lifecycle_sweep` block.

**First sweep result (2026-07-28):** 158 boards probed · 157 swept · 1 skipped ambiguous · 0 errored · **69 jobs closed live→stale** · 22,054 live rows stamped `last_polled_at` · 22,055 fresh_ids on sources · top closed: carvana 29, spacex 5, onemedical 4.

**Feed surface:** `GET /api/v1/jobs/feed` now returns a `discovery` block with `{polled_at, sweep_id, boards_swept_last_pass, closed_last_pass}` — "live" on the feed = "present on source board as of last successful poll", and that timestamp is explicit.

### 5.1b Apply-at-birth tiered polling — SHIPPED (behind env flag)

`backend/services/apply_at_birth.py` + `backend/tools/apply_at_birth_report.py`.

* Velocity classifier: `HOT (>=5 postings inserted in last 24 h)`, `WARM (>=1 in last 7 d)`, `COLD (else)`.
* Tier intervals: HOT=20 min, WARM=2 h, COLD=6 h (env-tunable via `APPLY_AT_BIRTH_{HOT,WARM,COLD}_INTERVAL_S`).
* Delta detection composes `lifecycle_sweep.sweep_one` — one fetch per poll, no double-poll.
* `next_due_at` per (source_ats, employer_token) stored in `apply_at_birth_state`; per-tick audit in `apply_at_birth_ticks`.
* **Median posting→queue metric** filters honestly — only counts rows whose `posted_at` AND `first_seen` are both within the window (not the initial ingest sweep-up).
* Kept BEHIND an env flag; scheduler auto-wiring intentionally deferred per rail "no new automation without approval". Report from current state: `apply-at-birth · tiers hot=147 warm=10 cold=1 · median_posting_to_queue_minutes_last_24h=234.5` (mostly-hot classification reflects today's initial 158-tuple ingest — tiers normalise over the following weeks).

### 5.1c Pre-flight simulate endpoint

`POST /api/v1/preflight/simulate` (`backend/domains/preflight/`). Read-only dry-fire of `preflight_check` — same auth (session cookie + CSRF) and consent gate (`submit_applications`) as the real dispatch, but NO persist / NO state change / NO receipt-outbox writes. Verified live: block path returns `ok=false` + full verdict (no side-effect audit rows written); pass path returns `ok=true` with clean verdict; unauth call returns HTTP 403 CSRF (auth-gated as designed).

### 5.2 Shared form-map cache — SHIPPED

`backend/services/form_map_cache.py`.

* Key: `(ats, form_fingerprint)`; fingerprint = sha256 of sorted `(name, type, required)` tuples — deterministic across field reordering.
* Value: `{selector_map, fill_confidence, verified_at, verified_by_count, verified_by_sources, status}`.
* One verified fill promotes the map for ALL users; `demote(ats, fingerprint, reason)` zeroes confidence and marks `status=demoted` (never deletes — full audit via `demote_events`).
* **Structure only**: selector_map is sanitized so callers can NEVER smuggle user data — only `{selector, role, confidence}` are stored (test locks it in).
* **Bootstrap from sanctioned dry-run only** (rail): `bootstrap_from_dryrun_json(path)` reads the authoritative dry-run JSON, records URL-fingerprint entries with `structure_captured=False` for the 20 real GH/Lever forms already verified. Field-level fingerprints will require an explicitly-authorized future harness pass. Bootstrap complete: **20 form-maps recorded**, all `verified` status.

### 5.3 Outcome autopilot — SHIPPED

`backend/services/outcome_autopilot.py`.

* Per-app ledger: `application_outcomes` collection, kinds `viewed / response / interview / rejection / silence`, `days_to_response` derived from `submitted_at`.
* `compute_group_stats(user_id, group_by='employer' | 'resume_version_id')` → per-group counts + response_rate + median days-to-response.
* `reallocate_daily_budget(user_id)` → weekly reallocation weights employers by response rate; **every allocation carries a displayable `reason` string** so the UI renders "why fewer apps to X" honestly. Zero-signal fallback → equal weighting (never zero-out an employer without cause).
* `kill_list_candidates(user_id, silence_threshold, silence_days)` → identifies silent employers without auto-adding to the kill list; `add_to_kill_list` is idempotent; `restore_from_kill_list` is reversible with its own audit event.

### 5.4 Self-healing — SHIPPED

`backend/services/self_healing.py`.

* `threshold_check(form_map, threshold=CONFIDENCE_THRESHOLD)` — env-tunable via `SELF_HEALING_CONFIDENCE_THRESHOLD` (default `0.7`).
* `downgrade_map_to_assisted(ats, fingerprint, reason)` — wraps `form_map_cache.demote` and audits with `EVENT_MAP_DEMOTED_LOW_CONFIDENCE` (or `_FINGERPRINT_DRIFT` when reason contains "drift").
* `route_application_to_assisted(application_id, user_id, reason)` — sets `applications.state=assisted` + `assisted_reason`; `assisted_lane_reason(application_id)` powers the UI "Why is this in assisted lane?".
* `log_silent_failure` + `log_wrong_submission` — silent failure and wrong submission are FORBIDDEN; these helpers exist so the audit row is what makes any near-miss not-silent.

### Regression suite

`test_preflight_validator.py` (15) · `test_receipt_compound_index_regression.py` (5) · `test_consent_scope_enum_guard.py` (3) · `test_apply_at_birth.py` (6) · `test_form_map_cache.py` (8) · `test_outcome_autopilot.py` (5) · `test_self_healing.py` (7) · `test_phase3_safeguards.py` (34) · `test_phase4_and_unlock.py` (22) · `test_jd_parser.py` (9). **82 tests passing across focused Phase 3 / 4 / 5.0 / 5.1 / 5.2 / 5.3 / 5.4.**

---

## 🚦 Phase 5.0 — Pre-flight validator dispatch chokepoint — SHIPPED (2026-07-28)

**Rule (Founder Directive 2026-07-28):** "Before ANY outbound submission (email route now; real form/API later), machine-diff every outbound field and every resume line against the approved Passport claim it traces to. Untraceable line or mismatch → BLOCK and route to review lane with reason `validator_blocked_mismatch`. Validator verdict stored on the receipt. Zero unvalidated submissions by construction — enforced at the dispatch chokepoint so no code path can bypass it."

**Implementation:** `backend/services/preflight_validator.py`.

* **Composes** the existing line-level firewall (`services/validator.py`, which enforces claim traceability + number/year grounding + sealed-value leak scanning) and adds dispatch-surface checks: identity coherence, outbound-text grounding, sealed leak in outbound text, approved-claims-not-empty, materials manifest integrity.
* **Stable reason codes** (never rename without adjusting FE copy):
  * `validator_blocked_mismatch` — top-level, prepended on every block
  * `no_approved_claims` · `no_materials` · `manifest_mismatch`
  * `line_validation_failed:{n}` · `identity_mismatch`
  * `number_not_in_claims:{n}` · `date_not_in_claims:{y}`
  * `sensitive_leak:{claim_type}`
* **Channels:** `sprint_fixture`, `email_dry_run`, `email_live` (unused), `form_live` (unused; reserved for Phase 5 form autopilot).
* **On block:**
  1. Persist full verdict to `preflight_verdicts` (audit trail — every dispatch has a stored verdict, pass or block).
  2. Move application to `state="review"` with `review_reason="validator_blocked_mismatch"` and `review_verdict_id=<verdict id>`.
  3. Audit-log `preflight.blocked`.
  4. Return HTTP 422 with `{error, verdict.compact(), reasons, message}`.
* **On pass:** persist verdict + embed `verdict.compact()` under `submission_receipts.validator_verdict` — the receipt itself is proof the dispatch cleared the chokepoint.

**Chokepoint integration:**
* `backend/domains/submit_sprint/__init__.py::confirm_slot` — pre-flight runs BEFORE writing `submission_receipts` row.
* `backend/domains/email_route/__init__.py::dispatch` — pre-flight runs BEFORE writing `email_outbox` + `submission_receipts` rows.
* Static invariant tests (`test_preflight_validator.py::test_every_dispatch_chokepoint_calls_preflight_before_receipt` + `_blocks_on_unwilling_verdict` + `_embeds_verdict_on_receipt`) prevent future code paths from bypassing the validator.

**Live E2E replay against preview (2026-07-28):**
* Sprint confirm on shortlisted fixture app → **HTTP 200** (line-level validation passed against base resume manifest w/ 3 lines, 1 approved-claim reference each).
* Email-route dispatch with body signed `-- Fixture TestUser` when Passport identity is `Test Candidate FIXTURE` → **HTTP 422** `identity_mismatch`; app moved to `review` with `review_reason=validator_blocked_mismatch`; verdict persisted.
* Email-route dispatch with body signed `Sincerely, Test Candidate FIXTURE` → **HTTP 201** `duplicate=false`; verdict embedded on receipt.

**Regression suite:** `backend/tests/test_preflight_validator.py` — **14 passed**. Focused Phase 3/4/5 suite total: **41 passed**.

## 🚦 Catalog expansion 122 → 158 verified tuples — SHIPPED (2026-07-28)

`backend/domains/discovery/catalog.py` now carries **158 verified board tuples**: GH 96 + Lever 6 + Ashby 56. Every added tuple was probed live by `backend/tools/catalog_expand.py` and only kept when `boards-api.greenhouse.io` / `api.lever.co/v0/postings` / `api.ashbyhq.com/posting-api/job-board` returned **HTTP 200 with `n_jobs > 0`**. Never guessed; every failed candidate is dropped honestly and never appended.

**Scheduler ingest after expansion:** kept 157 (1 GH candidate returned 0 postings at ingest despite verifying earlier — honestly dropped); **22,053 live discovery postings** (GH 18,010 + Lever 565 + Ashby 3,478); **157 distinct employers**; lane: career 18,923 / income_now 3,211; Phoenix radius: 25 mi 262 / 60 mi 271.

## 🛰️ 200-URL route census (post-expansion) — RUN (2026-07-28)

`route_census_runs.id = census-1785193176`: **157 employers · 99.91 s · concurrency=8 · strict per-host `asyncio.Lock`**. Classification: `ashby 56 · gh-noCap 56 · portal-other 38 · lever-cap 6 · timeout 1`.

**Diff vs baseline** (`route_census_diffs.id = census-diff-1785193379`): every previously-classified employer kept its classification (`flipped=0, http_changed=0, retry_climb=0`). All 36 newly-added tuples landed cleanly: `ashby +12 · gh-noCap +14 · lever-cap +3 · portal-other +7`. Zero new-host degradations, zero existing-host drift.

## 🛠️ Census-diff ops tool — SHIPPED (2026-07-28) — P2

`backend/tools/route_census_diff.py` — read-only ops tool. Compares the two most recent `route_census_runs` docs and reports `class_shifts`, `flipped`, `http_changed`, `retry_climb`, `new_hosts`, `dropped_hosts`. Persists a single diff row per invocation to `route_census_diffs`. Never re-probes employer origins — pure derivation from already-persisted state.

## 📦 Discovery-evidence release-decision packet

`/app/docs/DISCOVERY-EVIDENCE.md` — every claim → artifact traceability index. Includes: branch + HEAD; live counts; both census passes with diff; 20/20 dry-run authoritative pass; email-route dry-run status; config-required items (USAJOBS, live SMTP); what remains unverified.

## 📊 Job-count reconciliation (2026-07-28)

`jobs=20,458→22,069 · all status='live' (no other lifecycle state exists) = GH 18,010 + Ashby 3,478 + Lever 565 + seed 16` across **157 distinct employers**. Founder's `4,994/19,655/3,512` figures diverged because they were three time-lagged snapshots of the same single-lifecycle pool: `4,994` = partial mid-scheduler snapshot; `19,655` = stale earlier PRD claim (~19,725) before today's 9 idempotent refresh passes + 158-tuple catalog expansion; `3,512` ≈ lane=income_now filter (now 3,211). No expiry/purge/supersession sweep exists.

---

## 🚦 Phase 4 · P0 fix — `submission_receipts` compound-index collision — VERIFIED (2026-07-28)

**Root cause (repro'd twice by independent tester):** the `submit_sprint` and `email_route` receipt writers inserted directly with `company_id=null` and `req_ref=null`. MongoDB's compound unique index `uniq_receipt_per_user_company_req = (user_id, company_id, req_ref)` treats nulls as equal, so a sprint receipt at `(user, null, null)` blocked the first email-route dispatch's receipt insert with `pymongo.errors.DuplicateKeyError E11000`. The outbox row still persisted, so the second call returned 201 with `duplicate=true`, masking the regression as normal dedup.

**Fix (`backend/domains/submit_sprint/__init__.py` + `backend/domains/email_route/__init__.py`):** every receipt writer now populates deterministic non-null values:

| Route             | `company_id`                                              | `req_ref`                                    |
|-------------------|-----------------------------------------------------------|----------------------------------------------|
| sprint_fixture    | `application.company_id` → `job_snapshot.company_id` → `canonical_key.split("::")[0]` → `sampleco.demo` | `sprint:slot:{slot_id}`                       |
| email_dry_run     | same waterfall → deterministic sentinel `email-route:{outbox_id}` | `email-route:outbox:{outbox_id}`             |

The Phase 5 real-submit path (`applications/service.py::submit`) already went through `receipts_svc.insert()`, which hard-fails on any falsy required field — those receipts were never null. That helper stays as the invariant floor.

**Live E2E replay against preview backend (2026-07-28):**
* `POST /api/v1/sprint/{sprint_id}/confirm` → 200 receipt id `fe84d623-…`.
* `POST /api/v1/email-route/dispatch` first call → **201** `duplicate=false` receipt id `c6455fe3-…` (previously 500).
* `POST /api/v1/email-route/dispatch` second call (same tuple) → 201 `duplicate=true` (real idempotent dedup, not masked collision).

**Regression suite:** `backend/tests/test_receipt_compound_index_regression.py` — 5 passed. Covers the static invariant (no receipt insert may omit `company_id`/`req_ref` or set them to `None`), the service-level falsy-input guard, and three concrete replays (sprint→email-route on same app, two sprint slots same company, two email-route dispatches same app different destinations).

---

## 🛰️ 200-URL route census — RUN (2026-07-28)

`python3 backend/tools/route_census.py --limit 200 --concurrency 8`, persisted to `route_census` + `route_census_runs`.

**Corrected classification split (persisted audit `route_census_runs.id = census-1785191820`):**

* `ashby` **44**, `gh-noCap` **42**, `portal-other` **31**, `lever-cap` **3**, `timeout` **1** — **121 distinct employers**, 36 distinct hosts, 72.72 s at concurrency=8.

**Honesty note:** the `--limit 200` request was honored but the sampler caps at the current discovery corpus size — `_sample_from_db` groups by `company_name` before sampling, and the corpus currently has exactly **121 distinct employers with `origin_url`**. So this pass covers **100 % of live discovery employers**, not 200. Expanding to 200 would require either (a) growing the discovery corpus past 121 distinct employers, or (b) explicit founder authorization to allow multiple URLs per employer in the census sampler (which would over-represent large employers).

**Per-host serialization was hardened before the run.** Previously the "1 s between hits" was measured from request START time, which at `concurrency=8` allowed parallel hits to the same host when a request took >1 s. Now the tool holds a per-host `asyncio.Lock` for the entire request lifecycle and stamps `host_last_hit` on request FINISH, so no employer origin ever sees more than one in-flight probe. Different hosts still run in parallel up to the concurrency semaphore.

---

## 🚦 Phase 4 · Item 4 — 20-form fill-and-abort dry-run — VERIFIED (2026-07-28)

**Branch:** `feat/real-job-discovery`. Preview-only. No merge, no deploy, no `.env` change.

**Evidence file:** `/app/docs/PHASE4-DRYRUN-EVIDENCE.md` (final authoritative pass at `2026-07-27T22:08:37`).
**Machine-readable audit:** `/app/docs/dryrun-screenshots/dryrun_1785185317.json`.
**Screenshots:** `/app/docs/dryrun-screenshots/dryrun_00.png` … `dryrun_19.png`.

### Final pass numbers (20 real GH + Lever URLs)
* Targets: **20** — 17 Greenhouse (`boards.greenhouse.io`, `job-boards.greenhouse.io`) + 3 Lever (`jobs.lever.co`).
* Filled + aborted: **20 / 20**.
* Fields-correct (email + name filled from fixture identity): **20 / 20**.
* Skipped-CAPTCHA: **0**.
* Failed: **0**.
* Non-GET attempts to employer origins that reached the wire: **0** (3 Cloudflare bot-detection telemetry XHRs were attempted by page JS and all 3 were `route.abort()`-ed by the harness BEFORE leaving the browser; none targeted `/apply`, `/submit`, `/candidates`, or any form-submission path).

### Harness fixes shipped this pass (2026-07-28)
1. `_load_urls` now strips inline ` #` comments — the candidate file has ` # Employer — Title` after each URL, which previously produced malformed URLs (HTTP 404).
2. `_detect_captcha` now checks the challenge iframe's computed style + bounding box, and only classifies an iframe as CAPTCHA-blocking when it's an actual challenge widget (`bframe`, `challenge.html`, `challenges/turnstile`) or covers ≥320×320 px. The tiny 256×60 reCAPTCHA / hCaptcha **badge** that Greenhouse ships on every protected form is intentionally excluded — it does not block field autofill and is only enforced at submit time (which we never do).
3. Submit-button neutralization tightened to strict `input[type=submit]` / `button[type=submit]` / exact "Submit", "Submit application", "Send application" text. Generic `<button>Apply</button>` / `<a>Apply</a>` reveal buttons are preserved so the form section can actually appear.
4. Added a "reveal Apply" click step for Greenhouse `boards.greenhouse.io` pages that hide the application form behind a top Apply CTA.
5. Added a triple-layered submit guard: element neutralization + `form.submit()` monkey-patch + `submit` event `preventDefault/stopPropagation` — plus the context-wide route `_guard` that aborts every non-GET request at the wire. Defense in depth.
6. Every non-GET the browser attempts is now recorded with `{method, url, host, resource_type}` so we can prove zero form-submission requests reached any employer origin.

### Fixture identity used (test data only)
- Name: `Fixture TestUser`
- Email: `fixture-dryrun@opportunityos.dev`
- Phone: `+1-555-0100`
- LinkedIn: `https://www.linkedin.com/in/fixture-testuser`

## 🚦 Phase 4 · Item 3 (blocker fix) — `submit_applications` consent scope — VERIFIED (2026-07-28)

**Consent scope registered as first-class in `backend/core/policy.py` +
`backend/domains/consent/models.py`.**

- Fixture-user seed grants `submit_applications`.
- `GET /api/v1/consents/scopes` returns the scope in the enumerable list.
- Enum-coverage test: `backend/tests/test_consent_scope_enum_guard.py` (3 passed).

### Email-route E2E — VERIFIED (2026-07-28)

Curl against preview URL with fixture cookies + CSRF:

```
POST /api/v1/email-route/dispatch   → 201
  id=4d89357d-…86  state=dry_run  sent_to_smtp=false  provider=local_sink
  duplicate=false  receipt_id=21e4a747-…f6

POST /api/v1/email-route/dispatch   → 201  (same {user, app, dest})
  id=4d89357d-…86  (identical)  duplicate=true   ← dedup by sha256(user_id::app_id::dest)

GET  /api/v1/email-route/outbox     → row persisted, state=dry_run
```

### Low-supply credential-unlock prompt (Feed) — VERIFIED (2026-07-28)

- Fixture user has **9 passing** jobs (below the `LOW_SUPPLY_THRESHOLD = 15`).
- Prompt rendered at `data-testid=feed-low-supply-credential-unlocks`
  BELOW the passing cards, NOT duplicating `TruthfulEmpty`.
- Confirmed truthful copy: live count ("Only 9 job(s) pass your gates …"),
  live-source disclaimer, and 3 credential rows: `+6 jobs` CCMA (12–32 wks · $1,500–$5,000),
  `+4 jobs` Phlebotomy Tech (6–16 wks · $600–$2,500), `+2 jobs` CDL Class A
  (3–8 wks · $3,000–$7,000). Each row surfaces the catalog's official
  verification URL (NHA / ASCP / AZ MVD).
- Screenshot: `/app/docs/dryrun-screenshots/feed_low_supply.png`.

## 🧾 Bulk-prepare cost — one-line honesty answer (2026-07-28)

**The fixture path is NOT non-LLM by design.** `bulk_prepare` → `apps_svc.prepare_application` runs the same two-attempt Claude Sonnet 4.5 pipeline for every application regardless of whether the underlying job is a SampleCo fixture or a real Greenhouse/Lever/Ashby row. A prepare that shows `$0.00 / 0 tokens` means BOTH LLM attempts failed validation and the deterministic `template_fallback_lines` builder produced the resume (recorded as `model=template:v0.1, tokens_in=0, tokens_out=0, cost_usd_est=0.0`). Priced Claude path: `$0.003/1K input + $0.015/1K output` (source table `_PRICE_TABLE_PER_1K` in `services/llm.py`, tagged `anthropic:public_2026-02`) — for a typical prepare (~4K tokens in / ~800 tokens out) that's ≈ **$0.024 per successful attempt**.

---

## 🚦 Phase 3 (Founder Brief · Real-Job Discovery lane) — SHIPPED (2026-07-27)

**Active branch:** `feat/real-job-discovery`.
**Latest checkpoint (Phase 3 batch):** `dfb83a6b` (+ two hot-fix commits below).
**Backend regression this phase:** **51/51** — 23 `test_gate_engine.py` + 11 `test_phase3_safeguards.py` + 14 `test_phase3_integration_live.py` + 3 `test_iter20_walkin_and_chips.py`. See `/app/test_reports/iteration_20.json` (`retest_needed=false`).

### What shipped

1. **Degree-blind eligibility.** `services/gate_engine.py` — only three gate families may hard-exclude a job: work authorization (`work_auth` · `itar` · `sponsorship` · `stem_opt_viability`), legally-mandatory `licensure`, and geographic impossibility (`location_onsite`). `education_requirement` and `experience_band` now emit `status="pass"` with a visible NOTE for any mismatch. `evaluate()` returns a `notes` list; `/api/v1/jobs/feed` and `/api/v1/jobs/{id}` propagate it so the UI can render "Job requests PhD; your highest approved degree is MS. Degree is not a hard exclusion." on the card.
2. **Precise licensure hard-fail.** `_LEGAL_LICENSE_PATTERNS` covers 27 statutory credentials (CDL, RN, LPN, LVN, NP, CNA, MD, DO, DDS/DMD, PA, LCSW/LMSW/LMFT/LPC, EMT/Paramedic, PE, CPA, Bar admission, Real Estate, Electrician/Plumber/HVAC/Contractor, FINRA Series, Insurance Producer, Pharmacist, Pharmacy Tech, Radiologic Tech, Cosmetology/Barber, Childcare, State Teaching, DEA registration, Security Guard). Missing legally-mandatory license → `status="fail"`, `reason=missing_legal_license:<label>`. Ambiguous credentials (PMP, AWS certs, OSHA-30, etc.) → `status="pass"` + note. Over-filtering is the failure mode.
3. **Rolling 30-day employer cap.** `services/employer_cap.py` — 3 open applications per employer per 30-day window. Enforced in `applications/service.py::shortlist` → `EmployerCapReached`; router translates to HTTP 429 with `detail.error="employer_cap_reached"`, cap, window, and human-readable message. Frontend `Feed.jsx` surfaces the flash.
4. **Income velocity estimator + Lane B sort.** `services/velocity.py` — deterministic (no LLM) hourly-rate parse from JD/comp, salary→hourly fallback, part-time detection, staleness decay. `/jobs/feed?sort=velocity` (alias `soonest_money`) sorts passing rows by `velocity_score` DESC. Every job card carries a fully-shaped `velocity{hourly_rate_usd, hours_per_week, weekly_est_usd, posted_days_ago, velocity_score}`.
5. **Supply-Reality dashboard.** `GET /api/v1/dashboard/supply-reality` — `supply{live_jobs, live_by_lane{career, income_now}, new_today, within_25/60mi_of_phoenix}`, `budget{plan, daily_submit_cap, submitted_today, budget_remaining_today}`, `employer_cap{cap=3, window_days=30, top_employers_last_30d[]}`, `backlog{open_applications}`.
6. **Credential-to-Income catalog.** `domains/credentials` — 9 seed credentials (CDL Class A, CNA, EMT-B, Phlebotomy, Certified MA, Forklift OSHA, AZ Food Handler Card, AZ Fingerprint Clearance, AZ Security Guard). Each carries typical_hourly range, time_to_credential range, approx_cost_usd range, `mandatory` bool, and links to the authoritative AZ / national body. `GET /api/v1/credentials/catalog` + `GET /api/v1/credentials/{id}`.
7. **Walk-in Route Log.** `domains/walkin` — append-only ledger of in-person applications; each walk-in auto-provisions a companion `applications` row (route=`walkin`, synthetic `job_id=walkin:<uuid>` to avoid unique-index collision). `POST /api/v1/walkins` + `GET /api/v1/walkins/mine`. 5-per-hour rate limit.
8. **Persona variants.** `domains/persona` — user-owned labeled slices of approved claims for downstream Phase 4 resume tailoring. `POST/GET/PATCH /api/v1/personas`. Only APPROVED, non-sealed claim IDs may be pinned (400 `claim_ids_not_approved_or_missing` otherwise). Append-only versioning (v+1 with `superseded_by`).
9. **Frontend Lane UI + truthful empty state.** `Feed.jsx` — `LaneTabs` (All/Career/Income Now), `SortSelector` (Best fit / Nearest Phoenix / Soonest money), auto-suggests `sort=velocity` when Income Now is picked, `VelocityChip`/`LaneChip`/`DistanceChip` with data-testids, notes list on every card, `TruthfulEmpty` state that shows top exclusion reasons + `Widen my preferences` CTA instead of a bare empty screen.

### Fixes on top of the checkpoint (2026-07-27)

- **CRITICAL** — `POST /api/v1/walkins` was 500-ing on the 2nd walkin per user because the companion applications row's `job_id:null` collided with the `uniq_open_app_per_user_job` unique index. Fixed by synthesizing `job_id=f"walkin:{uuid.uuid4()}"` per walkin.
- **MEDIUM** — Added `data-testid` on `VelocityChip` / `LaneChip` / `DistanceChip` so automation can assert chip presence.
- **LOW** — SampleCo seed now stamps `lane="career"` and `distance_from_phoenix_mi` so the chips render for the deterministic fixture user; `_rebase_fixture_user` `to_wipe` list now includes `walkins` and `personas`.

### Rails (unchanged)

- Preview-only. **No merge, no push, no publish, no deploy, no production DB writes, no `.env` edits, no real employer submissions.**
- `feat/lynk-premium-autopilot` remains deferred and MUST NOT be merged into discovery.
- USAJOBS adapter is CONFIG-REQUIRED. Founder-only registration at https://developer.usajobs.gov; env vars `USAJOBS_API_KEY`, `USAJOBS_USER_AGENT_EMAIL`.

---

## 🚦 Phase 2 (Real-Job Discovery lane) — SHIPPED (2026-07-27)

**Discovery corpus:** 19,725 real live postings from Greenhouse/Lever/Ashby public APIs across 114+ verified employers (Greenhouse 16,204 · Ashby 3,032 · Lever 489). Lane B = 2,953 (Income Now). Within 25 mi Phoenix = 244 (68 Lane B). Six-hour scheduler + manual refresh (`POST /api/v1/discovery/refresh`) + per-run audit trail in `discovery_runs`. USAJOBS remains CONFIG-REQUIRED.

**Skipped sources (documented, no compliant public JSON):** NEOGOV / governmentjobs.com portals (Phoenix/Tempe/Mesa/Scottsdale/Chandler/Maricopa/AZ State), AZ K-12 vendor portals (Frontline/PowerSchool/TalentEd), ASU Workday cxs.

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

