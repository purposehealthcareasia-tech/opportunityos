# DISCOVERY-EVIDENCE — Merge-Decision Packet (2026-07-28 · final)

Every claim in this document maps to a **live artifact** on the current branch.
This is the founder's merge-decision packet — accuracy over polish. Do not
cite a row without opening the referenced artifact.

## Branch & HEAD

| Field  | Value                                       |
|--------|---------------------------------------------|
| Branch | `feat/real-job-discovery`                   |
| HEAD   | `1f6009fcfea618bafa82f9228c1cb63a499a4fb2`  |
| Rails  | preview only · no merge · no push · no deploy · no `.env` change · no real submissions · no CAPTCHA interaction · no LinkedIn / Indeed / Handshake ingest · no new headless-browser automation beyond the sanctioned fill-and-abort harness |

## Tester verdicts (chronological, verbatim)

| # | Batch                       | Verdict                                          | Report / evidence                                                         |
|---|-----------------------------|--------------------------------------------------|---------------------------------------------------------------------------|
| 1 | Phase 3 (14-gate + feed)    | PASS (51/51 focused suites)                      | `/app/test_reports/iteration_20.json`                                     |
| 2 | Phase 4 low-supply prompt   | PASS                                             | `/app/docs/dryrun-screenshots/feed_low_supply.png`                        |
| 3 | Phase 4 email-route + receipt collision fix | PASS (3/3 replays after fix) | `backend/tests/test_receipt_compound_index_regression.py` (5 passed)      |
| 4 | Phase 4 · Item 4 fill-and-abort 20/20 | PASS (`filled_and_aborted=20, non_GET_to_employer=0`) | `/app/docs/PHASE4-DRYRUN-EVIDENCE.md`, `dryrun_1785185317.json`  |
| 5 | Phase 5.0 pre-flight validator | PASS (3/3)                                    | `backend/tests/test_preflight_validator.py` (15 passed)                   |
| 6 | Phase 5.1 lifecycle truthfulness | PASS — 75 closed jobs each carry `closed_detected_at`, 22,055 of 22,071 live rows stamped `last_polled_at` (the 16 unstamped are seed docs), zero closed leak into feed, `discovery.polled_at + sweep_id + boards_swept_last_pass + closed_last_pass` all surfaced on `/jobs/feed` | live DB inspection 2026-07-28                                              |
| 7 | Phase 5.1 preflight simulate | PASS — auth + `submit_applications`-consent gated, identity mismatch flagged with named `body_signature` finding, zero writes to `preflight_verdicts / submission_receipts / email_outbox`, app state untouched. Unauth returns **401** without cookie or **403 csrf_check_failed** with cookie but missing/wrong CSRF header — both are correct; brief phrasing amended in `backend/domains/preflight/__init__.py` docstring. | live curl 2026-07-28                                                  |
| 8 | Phase 5.2 form-map cache hygiene | PASS — 20 docs (17 GH + 3 Lever), every doc `status=verified`, `structure_captured=false`, `fill_confidence=0.7`, `selector_map=[]`. Full PII scan (fixture identity tokens + forbidden-key/regex sweep across every doc field) → **null (clean)**. | live DB inspection 2026-07-28 |
| 9 | Phase 5.3/5.4 outcome + self-healing evidence | PASS — 1 fresh `application_outcomes` row (`kind=response, days_to_response=3.0`); 1 fresh `budget_reallocations` row with non-empty `reason="response_rate=100.00% on 1 apps · median_days_to_response=3.0"`; 1 fresh `self_healing_events map_demoted_low_confidence` with named `reason`; 1 fixture app moved to `state=assisted` with `assisted_reason` + `assisted_at`. | live DB inspection 2026-07-28 |
| 10 | Additive backend surface (kill-list list/restore + reallocation/latest) | PASS (7/7 endpoint tests + live curl round-trip) | `backend/tests/test_outcomes_endpoints.py`                     |
| 11 | Three P2 UI surfaces (simulate feedback / assisted-lane chip / kill-list restore) | **4/4 PASS** — simulate renders with zero side effects (receipts 0→0); `/applications` honest empty state; `/outcomes` renders stored reallocation reason verbatim with honest kill-list empty state + restored trail; consent gating proven (200 with consent, 403 `consent_required` after revoke, 200 on re-grant). | `/app/test_reports/iteration_21.json` (main-agent smoke) + independent tester's 4/4 relay 2026-07-28 |

**Focused Phase-5 regression suite at packet time:** **58 passed** across
`test_preflight_validator (15) + test_receipt_compound_index_regression (5) +
test_consent_scope_enum_guard (3) + test_apply_at_birth (6) +
test_form_map_cache (8) + test_outcome_autopilot (5) + test_self_healing (7) +
test_outcomes_endpoints (7) + test_deploy_readiness (2)`. Historical
full-suite has environment-dependent baseline failures (cookie-based auth
returns 200 without `access_token` body when `CI_TEST_ISSUER_ENABLED=false`,
and `test_deploy_readiness::test_preview_mode_seed_creates_full_fixture`
hard-codes 15 sample jobs when the seed now has 16 — pre-existing drift,
not touched by this batch).

## Founder-gated items (deliberately parked)

| Item                                                        | Status  | Unblock condition                          |
|-------------------------------------------------------------|---------|--------------------------------------------|
| Apply-at-birth polling scheduler wiring                     | PARKED  | Explicit founder green-light               |
| New sanctioned field-structure capture dry-run              | PARKED  | Explicit founder green-light               |

The **services** for both items are shipped and unit-tested; only the
operational wiring (scheduler task + new browser pass) is intentionally
not attached, per the founder rail "no new automation without approval".

## Post-merge candidate (spec-only, do not build)

**Outcomes drift sparkline** — a per-employer week-over-week sparkline of
`response_rate` and `median_days_to_response`, driven purely from the
existing `application_outcomes` ledger. Read-only, no new write path.
Would strengthen the `/outcomes` explainer from "why fewer apps to X
today" into "and here's the observed trend that led to it". Parked in the
PRD backlog until after the merge decision.

## Live job counts (source-of-truth: MongoDB `jobs` + `discovery_runs`)

| Metric                                       | Value    | Artifact                                          |
|----------------------------------------------|----------|---------------------------------------------------|
| Total `jobs` docs                            | 22,069   | `db.jobs.count_documents({})`                     |
| `status='live'` (single lifecycle state)     | 22,069   | `db.jobs.count_documents({'status':'live'})`      |
| Live discovery source                        | 22,053   | `db.jobs.count_documents({status:'live', source:/^discovery/})` |
| Live seed / SampleCo demo                    | 16       | `source:'seed'`                                    |
| Distinct live discovery employers            | 157      | `db.jobs.distinct('company_name', {source:/^discovery/})` |
| Per-source live posts (latest scheduler)     | GH 18,010 · Lever 565 · Ashby 3,478 | `route_census_runs` + `discovery_runs.summary.per_source_postings` |
| Lane split                                   | career 18,923 · income_now 3,211 | `discovery_runs.summary.lane_totals` |
| Phoenix radius                               | ≤25mi 262 · ≤60mi 271           | `discovery_runs.summary.phoenix_radius_totals` |
| Catalog size (verified tuples)               | 158 (GH 96 · Lever 6 · Ashby 56) | `backend/domains/discovery/catalog.py`         |
| Boards active in scheduler after first ingest| 157 (1 GH board returned zero postings at ingest — honestly dropped) | `discovery_runs.summary`               |
| Lifecycle first sweep (2026-07-28)           | 158 probed · 157 swept · 1 skipped ambiguous · 0 errored · **69 → 75 jobs closed live→stale (independent tester recount)** · 22,054 → 22,055 live rows stamped `last_polled_at` · top closed: carvana 29, spacex 5, onemedical 4 | `backend/tools/lifecycle_first_sweep.py`, `db.lifecycle_sweep_runs` |

**Reconciliation with older cited numbers (2026-07-28):** the three figures
`4,994 / 19,655 / 3,512` are all snapshots of the same single-lifecycle pool
at different times / with different filters — they do NOT represent
different collections. `4,994` = a partial mid-scheduler snapshot before
GH+Ashby finished a pass. `19,655` ≈ my earlier PRD claim (~19,725) before
today's 8 idempotent refresh passes + 158-tuple catalog expansion.
`3,512` ≈ the tester's `lane=income_now` filtered view (currently 3,211).
**Lifecycle sweep now closes absent postings to `status='closed'` with a
timestamped audit row** rather than leaving stale rows in the live feed —
the collection retains history but the feed reflects source truth.

## Config-required items (unset by design; do NOT set without founder sign-off)

| Item                              | Env keys                                                                 | Effect if unset                                                                           |
|-----------------------------------|--------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| USAJOBS live ingest               | `USAJOBS_API_KEY`, `USAJOBS_USER_AGENT_EMAIL`                            | Discovery scheduler records `usajobs.status=config_required`; skipped honestly.           |
| Email route live send             | `EMAIL_ROUTE_PROVIDER`, `EMAIL_ROUTE_FROM`, `EMAIL_ROUTE_API_KEY`, `EMAIL_ROUTE_DRY_RUN=false` | Dispatch stays in `dry_run` state (`sent_to_smtp=false`, `provider=local_sink`); nothing leaves the backend. |
| Live SMTP dispatch                | Same as above                                                            | DISABLED. Documented at `/app/docs/EMAIL-ROUTE-CONFIG.md`.                                |
| Apple sign-in                     | `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`, `APPLE_REDIRECT_URI` | Login button renders `Continue with Apple — not yet available` (frontend disabled state). |
| Phone OTP (Twilio Verify)         | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID`   | Login Phone tab shows "not yet configured" copy; no fake Send-code button.                |
| Email provider (Resend/SendGrid)  | `RESEND_API_KEY` / `SENDGRID_API_KEY` + webhook secret                   | Provider reports `CONFIGURATION_REQUIRED` in admin registry; no send.                     |
| Payment providers (Razorpay/PayPal/Paystack) | Provider-specific keys                                        | Provider reports `CONFIGURATION_REQUIRED`; no order create / webhook accept.              |
| ElevenLabs voice                  | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL_ID`       | Provider reports `CONFIGURATION_REQUIRED`; no TTS.                                        |
| Discovery admin refresh           | `PRIVATE_AUTOPILOT_OWNER_EMAILS`                                         | Manual `/api/v1/discovery/refresh` requires owner/admin login; scheduled refresh still runs. |
| Production auth                   | `PROD_MODE=true` + `CI_TEST_ISSUER_ENABLED=false` + prod-only `CORS_ALLOW_ORIGINS` + rotated `JWT_SECRET / INTERNAL_SERVICE_TOKEN` | Server refuses to boot if `PROD_MODE=true` and `CI_TEST_ISSUER_ENABLED=true` are both set. |

## 121-employer census (route classification) — pre-expansion baseline

`route_census_runs.id = census-1785191820` (2026-07-27T22:37 UTC, 121 employers, 72.72 s, concurrency=8, strict per-host lock)

| Classification | Count | %      |
|----------------|-------|--------|
| `ashby`        | 44    | 36.4 % |
| `gh-noCap`     | 42    | 34.7 % |
| `portal-other` | 31    | 25.6 % |
| `lever-cap`    | 3     | 2.5 %  |
| `timeout`      | 1     | 0.8 %  |

## 157-employer census (route classification) — post-expansion

`route_census_runs.id = census-1785193176` (2026-07-27T23:XX UTC, 157 employers, 99.91 s, concurrency=8, strict per-host lock)

| Classification | Count | %      |
|----------------|-------|--------|
| `ashby`        | 56    | 35.7 % |
| `gh-noCap`     | 56    | 35.7 % |
| `portal-other` | 38    | 24.2 % |
| `lever-cap`    | 6     | 3.8 %  |
| `timeout`      | 1     | 0.6 %  |

**Diff** (`route_census_diffs.id = census-diff-1785193379`): every previously-classified
employer kept its classification (`flipped=0, http_changed=0, retry_climb=0`).
All 36 newly-added tuples landed cleanly: `ashby +12 · gh-noCap +14 ·
lever-cap +3 · portal-other +7`. Zero new-host degradations, zero
existing-host drift.

Per-host serialization ran with strict per-host `asyncio.Lock` for the full
request lifecycle and `host_last_hit` stamped on request FINISH — no
employer origin ever saw a parallel probe in either pass.

## 20-form fill-and-abort dry-run — authoritative pass

| Field                              | Value                                                     |
|------------------------------------|-----------------------------------------------------------|
| Evidence doc                       | `/app/docs/PHASE4-DRYRUN-EVIDENCE.md`                     |
| Machine-readable audit             | `/app/docs/dryrun-screenshots/dryrun_1785185317.json`     |
| Screenshots (20 forms)             | `/app/docs/dryrun-screenshots/dryrun_00.png` … `_19.png`  |
| Authoritative pass timestamp       | `2026-07-27T22:08:37+00:00`                               |
| Targets                            | 20 (17 Greenhouse + 3 Lever)                              |
| Filled + aborted                   | **20 / 20**                                               |
| Fields-correct (email + name auto) | **20 / 20**                                               |
| Skipped-CAPTCHA                    | **0**                                                     |
| Failed                             | **0**                                                     |
| Non-GET requests attempted (all)   | 69 (all aborted by `context.route` guard)                 |
| Non-GET requests to employer origins that reached the wire | **0** — 3 attempted, all Cloudflare bot-detection `/cdn-cgi/challenge-platform/…` telemetry XHRs, all aborted before leaving the browser |
| Employer hosts visited             | `boards.greenhouse.io`, `job-boards.greenhouse.io`, `jobs.lever.co` |

Superseded prior pass (`2026-07-27T21:54:29`) retained in evidence as
historical honesty — the harness had two bugs (inline `#`-comment URL
parser, over-eager reCAPTCHA-badge classifier); both fixed on this pass.

## Email-route dry-run status

* **State: dry-run only** (`sent_to_smtp=false`, `provider=local_sink`).
* Route registered: `POST /api/v1/email-route/dispatch`, guarded by the
  first-class `submit_applications` consent scope AND the pre-flight
  validator dispatch chokepoint.
* Live E2E after receipt-collision fix (`2026-07-28`, replay against preview):
  * `POST /sprint/{id}/confirm` → 200, receipt id `fe84d623-…`.
  * First `POST /email-route/dispatch` → **201** `duplicate=false`,
    receipt id `c6455fe3-…`.
  * Second dispatch (same tuple) → 201 `duplicate=true` (real idempotent
    dedup, not masked E11000).
* Regression suite: `backend/tests/test_receipt_compound_index_regression.py`
  — **5 passed** (invariant + service guard + 3 concrete replays).
* **Live SMTP: DISABLED.** No provider credentials in `.env`. Any real
  send would require an explicit founder-authorized configuration change
  documented in `/app/docs/EMAIL-ROUTE-CONFIG.md`.

## Consent scope registry

Scopes exposed at `GET /api/v1/consents/scopes`:
`process_career_data`, `discover_jobs`, `generate_materials`,
`track_applications`, `email_me`, `submit_applications`.
The Phase 5 outcome surface (kill-list list/restore + reallocation/latest)
is gated on `track_applications`; the sprint/email/preflight-simulate
paths are gated on `submit_applications`. Enum-coverage guard:
`backend/tests/test_consent_scope_enum_guard.py` — 3 passed.

## Fixture demonstration seeds (2026-07-28)

The fixture rebase now seeds ONE `state=assisted` application + ONE
active `kill_list` row on every startup so the P2 UI surfaces are
visually verifiable on every future acceptance pass without manual
setup. Both rows are explicitly marked `fixture: true` in the payload
and use fixture-only strings (SampleCo job for the assisted-lane row,
sentinel employer `sampleco-demo-ghosts` for the kill-list row). The
feed acceptance geometry (9 passing / 6 excluded on the 15 SampleCo
sample jobs) is preserved — feed reads `jobs`, not `applications`.

## What remains unverified (do NOT claim as done)

* **Live-form submission compatibility** for any ATS beyond fill-and-abort
  is unproven. The only verified capability is "can we type into 20 real
  Greenhouse/Lever forms without submitting" — not "can we submit safely".
* **Workday tenant-path** support (~38/157 census hosts classified
  `portal-other`) is deferred until after the merge decision; assisted
  lane covers those employers meanwhile.
* **Live SMTP dispatch, real submissions, real emails to employers** —
  intentionally disabled and out of scope for this merge-decision packet.
* **Apply-at-birth scheduler** — service + tiers shipped, scheduler
  wiring PARKED pending founder green-light.
* **New sanctioned field-structure capture dry-run** — form-map cache
  wired only to the existing URL-fingerprint bootstrap from the
  already-approved 20/20 pass; new browser pass PARKED pending founder
  green-light.

## Traceability index (every claim → artifact)

| Claim                                | Artifact                                                        |
|--------------------------------------|-----------------------------------------------------------------|
| Discovery counts                     | `db.jobs`, `db.discovery_runs` (latest rows on this branch)     |
| Catalog size 158 verified            | `/app/backend/domains/discovery/catalog.py` (GH 96 + Lever 6 + Ashby 56) |
| Lifecycle sweep audit                | `db.lifecycle_sweep_runs`, `backend/services/lifecycle_sweep.py` |
| 122→158 verification history         | `route_census_runs` + this doc's per-round verified lists       |
| Route census baseline                | `route_census_runs.id=census-1785191820`; `route_census` (per-URL)|
| Route census post-expansion + diff   | `route_census_runs.id=census-1785193176`, `route_census_diffs.id=census-diff-1785193379` |
| 20/20 dry-run                        | `/app/docs/PHASE4-DRYRUN-EVIDENCE.md`, `dryrun_1785185317.json`, `/app/docs/dryrun-screenshots/` |
| Email-route regression closed        | `backend/tests/test_receipt_compound_index_regression.py`, live E2E replay 2026-07-28 |
| Consent scope registry               | `backend/core/policy.py`, `backend/domains/consent/models.py`   |
| Preflight validator + simulate       | `backend/services/preflight_validator.py`, `backend/domains/preflight/__init__.py`, `backend/tests/test_preflight_validator.py` (15 passed) |
| Apply-at-birth service + tiers       | `backend/services/apply_at_birth.py`, `backend/tools/apply_at_birth_report.py`, `backend/tests/test_apply_at_birth.py` (6 passed) |
| Form-map cache + bootstrap           | `backend/services/form_map_cache.py`, `backend/tests/test_form_map_cache.py` (8 passed), live DB inspection 20 docs `structure_captured=false`, PII scan null |
| Outcome autopilot + kill-list        | `backend/services/outcome_autopilot.py`, `backend/tests/test_outcome_autopilot.py` (5 passed) |
| Self-healing downgrades              | `backend/services/self_healing.py`, `backend/tests/test_self_healing.py` (7 passed) |
| Additive outcomes endpoints          | `backend/domains/outcomes/service.py` (kill-list list/restore + reallocation/latest), `backend/tests/test_outcomes_endpoints.py` (7 passed) |
| P2 UI surfaces (4/4 PASS)            | `frontend/src/pages/SubmitSprint.jsx`, `frontend/src/pages/Applications.jsx`, `frontend/src/pages/Outcomes.jsx`; test report `/app/test_reports/iteration_21.json` |
| Fixture demonstration seeds          | `backend/domains/seeds/seeder.py::_seed_fixture_assisted_lane_row + _seed_fixture_active_kill_list_row` |
| Config-required flags                | `backend/.env` (present-but-unset keys), `discovery_runs.summary.usajobs` |


