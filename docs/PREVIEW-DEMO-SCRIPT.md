# Preview Demo Script — Discovery + Precision-Autopilot Lane

**Branch:** `feat/real-job-discovery` @ HEAD `1f6009fcfea618bafa82f9228c1cb63a499a4fb2`
**Preview URL:** https://lynk-preview-2.preview.emergentagent.com
**Sign in as:** `fixture-ead@opportunityos.dev` / `Fixture!Test1` — see `/app/memory/test_credentials.md` for the full fixture-user profile.

## Rails — read this first

* This walkthrough hits **preview only**. No merge, no push, no deploy, no `.env` edits, no real submissions, no live email, no scraping, no CAPTCHA interaction, no LinkedIn / Indeed / Handshake ingest.
* Every SAMPLE row is badged `SAMPLE`. Every fixture-seeded artifact carries `fixture: true` in the payload or a `FIXTURE seed` prefix in its human copy.
* All four flows below are read-only OR write only to the fixture user's own append-only ledger. Nothing you do here reaches an employer.
* If any step behaves differently than described, **stop** and report — the fixture rebase runs on every backend restart and should keep this script deterministic.

## Flow 1 · Feed → Shortlist (SampleCo, fixture-only)

**Rail check:** the feed reads real Greenhouse/Lever/Ashby postings from documented public APIs plus 15 SampleCo demo rows. Shortlisting a SampleCo row is a fixture write to the `applications` collection only.

1. Sign in with the fixture credentials. Land on `/feed`.
2. Confirm the passing card count is exactly **9** and the excluded panel reports **6** SampleCo exclusions (`requires_us_person=2`, `no_sponsorship_offered=4`). If the count differs on SampleCo geometry, the fixture rebase drifted — do not proceed; report the deviation.
3. Locate any SampleCo card (SAMPLE badge in the corner). Click **Shortlist**.
4. Observe the flash `Shortlisted → …`. No employer network call happens — Shortlist writes a row to `applications` with `state='shortlisted'`.

## Flow 2 · Simulate preview verdict (`/submit-sprint`, fixture-only)

**Rail check:** `POST /api/v1/preflight/simulate` is a read-only dry-fire of the pre-flight validator. Same auth + `submit_applications` consent gate as the real dispatch chokepoint, but zero persist, zero receipts, zero application state change.

1. Navigate to `/submit-sprint`. If Flow 1 completed a shortlist, at least one fixture slot appears in the queue preview list. Otherwise open `/feed` and shortlist a SampleCo card first.
2. Click **Start sprint (N slots)**. The queue enters `running` state.
3. On the first `queued` slot, click **Preview verdict** (`data-testid=sprint-slot-simulate-0`). The button briefly shows `Simulating…`.
4. A result panel appears immediately below the slot: **`Simulate: WILL PASS`** for a fresh SampleCo shortlist (every resume line traces to an approved Passport claim). Text ends with `— no side effects`.
5. To exercise the block path from this same UI (optional), you would have to alter the fixture's approved claims — do not do that in this demo. The BLOCK code path is unit-tested by `backend/tests/test_preflight_validator.py::test_preflight_sprint_channel_blocks_on_unapproved_claim_reference`.
6. Confirm nothing left the browser: `Network` panel in DevTools shows the `POST /api/v1/preflight/simulate` request return with the verdict body; no receipt / outbox POST fires. `/applications` still lists the slot at `state='shortlisted'`.

## Flow 3 · Assisted-lane reason chip (`/applications`)

**Rail check:** the fixture rebase seeds one application in `state='assisted'` on every backend restart. The row is pinned to a SampleCo `is_sample=True` job, badged `SAMPLE`, and its `assisted_reason` explicitly begins with `FIXTURE seed · form-map fill confidence dropped below threshold…`. Nothing here submits or emails.

1. Open `/applications`. The single fixture-seeded row shows the state pill **`Assisted lane`** (`data-testid=app-state-assisted`).
2. Click the chip **`Why assisted lane?`** (`data-testid=app-assisted-lane-chip-<id>`). A detail panel expands with:
   * **Reason:** the full `FIXTURE seed · form-map fill confidence dropped…` string, verbatim from `applications.assisted_reason`.
   * **Since:** the `assisted_at` timestamp.
   * An italic footnote: "no submission is sent while it is here".
3. Click the chip again — the detail panel collapses.
4. The chip renders **only** on rows where `app.state === 'assisted'`. All other rows carry the normal state pill only.

## Flow 4 · Outcomes: reallocation reason + kill-list restore (`/outcomes`)

**Rail check:** both endpoints are consent-gated on `track_applications`. `GET /api/v1/outcomes/reallocation/latest` returns the STORED `budget_reallocations` row verbatim — never recomputes on the request path (static invariant test locks this). `POST /api/v1/outcomes/kill-list/{employer}/restore` stamps `restored_at + restored_reason` on the existing row; the original row is preserved for the audit trail.

1. Navigate to `/outcomes` (sidebar link between Tracker and Analytics).
2. **Reallocation panel** (`data-testid=reallocation-panel`) — if an allocation exists for the fixture user, a row renders with:
   * `weight` badge (percentage),
   * `submitted` count and `response_rate`,
   * the STORED **`reason`** string verbatim (e.g. `response_rate=100.00% on 1 apps · median_days_to_response=3.0`).
   * If no allocation has been computed, the panel honestly says so (`data-testid=reallocation-empty`).
3. **Kill-list panel** (`data-testid=killlist-panel`) — one active row is fixture-seeded: `employer="sampleco-demo-ghosts"`, reason begins `FIXTURE seed · 5 silence outcomes…`.
4. Click **Restore** on `sampleco-demo-ghosts` (`data-testid=killlist-restore-sampleco-demo-ghosts`). The button briefly shows `Restoring…`.
5. The active row disappears; the same row appears under **Recently restored** with a `(user_restore)` tag; a success flash banner reads "Restored sampleco-demo-ghosts. Suppression cleared; the row is preserved on the audit trail."
6. Reload the page: the row remains under Recently restored (server-side truth). On the NEXT backend restart, the fixture rebase re-seeds an active `sampleco-demo-ghosts` row so this flow is exercisable again.

## What NOT to click during the demo

* Do NOT click **Confirm** on any sprint slot unless you explicitly want to write a fixture-sprint receipt (safe — writes to `submission_receipts` with `channel=sprint_fixture`, no employer contact — but changes state that would need a rebase to reset).
* Do NOT visit `/api/v1/discovery/refresh` — that triggers a real ATS pass. Scheduled discovery already runs behind the scenes.
* Do NOT attempt to unmask any sealed claim on `/passport` — sealed masking is v0.1-frozen and by design has no unmask surface.
* Do NOT enable any provider in `/admin/integrations` unless you have valid credentials — every provider hard-fails on missing secrets rather than mock-succeeding.

## If anything drifts, report — do not "fix" in preview

* Feed passing count ≠ 9 for the fixture user → fixture rebase drift; report.
* Simulate returns anything other than `WILL PASS` on a fresh SampleCo shortlist → claim / manifest drift; report.
* Assisted-lane row missing after cold boot → fixture seed regression; report.
* Kill-list `sampleco-demo-ghosts` missing after cold boot → same class of regression; report.
* Any 500-class response, unexpected 401 (missing session), or a `submission_receipts` write with a `null` `company_id` / `req_ref` → hard rail violation; report immediately.

## Traceability

* Backend endpoints: `backend/domains/preflight/__init__.py` (simulate), `backend/domains/outcomes/service.py` (kill-list list/restore + reallocation/latest), `backend/domains/applications/service.py` (state read).
* Frontend surfaces: `frontend/src/pages/SubmitSprint.jsx`, `frontend/src/pages/Applications.jsx`, `frontend/src/pages/Outcomes.jsx`.
* Fixture seeds: `backend/domains/seeds/seeder.py::_seed_fixture_assisted_lane_row` + `_seed_fixture_active_kill_list_row`.
* Merge-decision packet: `/app/docs/DISCOVERY-EVIDENCE.md`.
* Test credentials: `/app/memory/test_credentials.md`.

**Rails maintained throughout.** This script is documentation only — no code changes were made to add it.
