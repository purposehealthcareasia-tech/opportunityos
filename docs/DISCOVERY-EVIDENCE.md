# DISCOVERY-EVIDENCE — Release-Decision Packet (2026-07-28)

Every claim in this document maps to a **live artifact** on the current branch.
This is the founder's release-decision packet — do not cite it without
opening the referenced artifact.

## Branch & HEAD

| Field  | Value                                       |
|--------|---------------------------------------------|
| Branch | `feat/real-job-discovery`                   |
| HEAD   | `c8631912fb36bdf7b6b82fcd3421811f5adc8b7f`  |
| Rails  | preview only · no merge · no push · no deploy · no `.env` change · no real submissions · no CAPTCHA interaction · no LinkedIn / Indeed / Handshake ingest · no new headless-browser automation beyond the sanctioned fill-and-abort harness |

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

**Reconciliation with older cited numbers (2026-07-28):** the three figures
`4,994 / 19,655 / 3,512` are all snapshots of the same single-lifecycle pool
at different times / with different filters — they do NOT represent
different collections. `4,994` = a partial mid-scheduler snapshot before
GH+Ashby finished a pass. `19,655` ≈ my earlier PRD claim (~19,725) before
today's 8 idempotent refresh passes; the corpus grew via new-posting
inserts and the 158-tuple catalog expansion. `3,512` ≈ the tester's
`lane=income_now` filtered view (currently 3,211). **No expiry / purge /
supersession sweep exists**; the collection has one lifecycle state.

Latest scheduler pass details (`db.discovery_runs`, latest by `ts`):
`elapsed=97.58 s · companies_kept=157 · companies_dropped=1
· postings_seen=22,053 · inserted=2 · updated=22,051`. Idempotent — a
successive pass touches the same rows.

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
  first-class `submit_applications` consent scope.
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
`track_applications`, `email_me`, **`submit_applications`** (newly
added — gates every submission path: sprint, email-route, and any future
Phase 5 outbound flow). Enum-coverage guard:
`backend/tests/test_consent_scope_enum_guard.py` — 3 passed.

## Config-required items (unset by design; do NOT set without founder sign-off)

| Item                          | Env keys                                            | Effect if unset                                                |
|-------------------------------|-----------------------------------------------------|-----------------------------------------------------------------|
| USAJOBS live ingest           | `USAJOBS_API_KEY`, `USAJOBS_USER_AGENT_EMAIL`       | Discovery scheduler records `usajobs.status=config_required`; skipped honestly. |
| Email route live send         | `EMAIL_ROUTE_PROVIDER`, `EMAIL_ROUTE_FROM`, `EMAIL_ROUTE_API_KEY`, `EMAIL_ROUTE_DRY_RUN=false` | Dispatch stays in `dry_run` state; nothing leaves the backend. |
| Discovery admin refresh       | `PRIVATE_AUTOPILOT_OWNER_EMAILS`                    | Manual `/api/v1/discovery/refresh` requires an owner/admin login; scheduled refresh still runs. |

## What remains unverified (do NOT claim as done)

* **Live-form submission compatibility** for any ATS beyond fill-and-abort
  is unproven. The only verified capability is "can we type into 20 real
  Greenhouse/Lever forms without submitting" — not "can we submit safely".
* **Workday tenant-path** support (~31/121 census hosts classified
  `portal-other`) is deferred until after the merge decision; assisted
  lane covers those employers meanwhile.
* **Phase 5** pre-flight validator, apply-at-birth polling tiers, shared
  form-map cache, outcome autopilot, and self-healing paths are DESIGNED
  in the founder directive but NOT yet implemented on this branch.
* **Live SMTP dispatch, real submissions, real emails to employers** —
  intentionally disabled and out of scope for this release-decision packet.

## Traceability index (every claim → artifact)

| Claim                                | Artifact                                                        |
|--------------------------------------|-----------------------------------------------------------------|
| Discovery counts                     | `db.jobs`, `db.discovery_runs` (latest 33 rows on this branch)  |
| Catalog size 158 verified            | `/app/backend/domains/discovery/catalog.py` (GH 96 + Lever 6 + Ashby 56) |
| 122→158 verification history         | `route_census_runs` + this doc's per-round verified lists       |
| Route census baseline                | `route_census_runs.id=census-1785191820`; `route_census` (per-URL)|
| 20/20 dry-run                        | `/app/docs/PHASE4-DRYRUN-EVIDENCE.md`, `dryrun_1785185317.json`, `/app/docs/dryrun-screenshots/` |
| Email-route regression closed        | `backend/tests/test_receipt_compound_index_regression.py`, live E2E replay 2026-07-28 |
| Consent scope registry               | `backend/core/policy.py`, `backend/domains/consent/models.py`   |
| Config-required flags                | `backend/.env` (present-but-unset keys), `discovery_runs.summary.usajobs` |
