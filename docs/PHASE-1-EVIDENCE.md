# PHASE 1 — CONVERSION LAYER · Merge-Decision Evidence (living document)

**Branch:** `feat/liquid-ui` (Phase 0 stacked lane, retroactively upgraded to full triple-source PASS via §16 of `PHASE-0-EVIDENCE.md`).
**Rails:** preview only · no merge · no push · no deploy · no `.env` edits · no real submissions · no live email · consent-gated everything · cap NEVER bypassed · wave authorizations logged with scope snapshot · follow-ups never auto-sent.

**Cycle policy (founder directive 2026-08-06):**
* **Atomic reload** — one uvicorn `--reload` for the entire opener + Phase-1 bundle in this exact order: (i) backend rebrand · (ii) scorer-unfreeze with byte-identical proof · (iii) Lighthouse re-measure · (iv) 1a speed-sort · (v) 1b Apply Wave · (vi) 1c booking URL · (vii) 1d follow-up drafts.
* **Gate preserved** — each Phase-1 item still lands with its own evidence section here (focused tests + honest failure states); full Phase-1 tester pass runs at phase end.

---

## §0 — Measured baseline (pre-cycle, 2026-08-06 ~11:00 UTC)

```
python3 -m pytest tests/test_preflight_validator.py tests/test_receipt_compound_index_regression.py \
                  tests/test_consent_scope_enum_guard.py tests/test_apply_at_birth.py \
                  tests/test_form_map_cache.py tests/test_outcome_autopilot.py \
                  tests/test_self_healing.py tests/test_outcomes_endpoints.py \
                  tests/test_surprise_me.py -q --tb=line
```
Result: **62 passed, 0 failed** (measured pre-cycle, unchanged from Phase 0 closeout).

**Fixed-fixture score snapshot for byte-identical proof** (`GET /api/v1/jobs/feed` as `fixture-ead@`, normalized by stripping volatile fields — `discovery`, `polled_at`, `last_polled_at`, `first_seen`, `posted_at`, `served_at`, `cache_key`, `fetched_at`; passing/excluded arrays sorted by `id`):
* `passing_count = 9`, `excluded_count = 22440`
* `passing_scores` (id_prefix, score) sorted by id:
  ```
  00cef519 → 91.97      04e6972b → 91.97      11b20e71 → 75.9
  184814d9 → 91.97      7d1e68b5 → 83.94      d646436d → 75.9
  e0fdf883 → 91.97      e5413a1f → 51.83      f3fad7cc → 83.94
  ```
* `md5(normalized_feed_pre.json)` = **`af9fb9e581ff1a4258bd3dddbc34cdc0`**

---

## §1 — Cycle log (append-only as items land)

### Step (i) — Backend rebrand · LANDED 2026-08-06T~13:00Z
- Files touched (user-facing strings only, per founder rail): `backend/server.py` (FastAPI title + shutdown log), `backend/services/llm.py` (SYSTEM_PROMPT + TAILOR_SYSTEM_PROMPT — model-visible product name), `backend/tools/catalog_expand.py` (UA), `backend/tools/route_census.py` (UA + docstring), `backend/tools/fill_and_abort.py` (fixture co name + UA), `backend/domains/seeds/data.py` (Admin/Support display names), `backend/domains/seeds/seeder.py` (EEO consent copy on SampleCo Q blocks), `backend/core/policy.py` (4 consent scope descriptions). Total: 11 replacements across 8 files.
- Held back per founder rail: internal Python docstrings/comments in `backend/domains/auth/google_service.py`, `backend/domains/auth/router.py`, `backend/domains/employer_intake/__init__.py` (dev-facing only, not user-facing prose).
- Frontend defensive fallback (`frontend/src/lib/consentScopes.js`) — comment + `CONSENT_SCOPES_FALLBACK` copy updated to reflect the backend rebrand is now live; helper stays as a floor so a stale cached policy payload never resurfaces the legacy brand.
- Rebrand grep sweep after edits: 0 remaining "OpportunityOS" occurrences in user-facing backend strings; only dev-facing comments retained by design.

### Step (ii) — Scorer unfreeze · LANDED 2026-08-06T~13:15Z · BYTE-IDENTICAL PROVEN
- New module: `backend/services/scored_cache.py` — process-lifetime LRU (bounded at `FYND_SCORED_CACHE_MAX`, default 500,000) keyed by `(md5(user_ctx_sig), job_id, job.last_verified_iso, weights_version)`. `ctx_signature()` folds in `preferences`, `eligibility`, approved-skills/education/employment/certifications, `existing_applications`, `hidden_job_ids` so ANY user-side state change auto-invalidates their rows.
- Wired into `backend/domains/jobs/router.py::feed` — the per-job loop now calls `scored_cache.get_or_compute(ctx, job, ctx_sig=…)` instead of `evaluate()` + `score_job()` directly. Same `evaluate()` + `score()` functions run on cache miss; hit returns the exact tuple stored on first compute. Zero change to weight tables, gate rules, or scoring math.
- **Byte-identical proof over stable intersection** (probe: `backend/tools/feed_hash_probe.py`; artifacts: `docs/phase-1-artifacts/feed_pre_unfreeze.json` + `feed_post_unfreeze_cold.json`; diff script embedded in evidence commit):
  * `pass_common_count = 9`  (all 9 passing jobs match by id)
  * `exc_common_count = 22440` (all 22,440 excluded jobs from pre-set are present in post-set)
  * `pre_stable_md5 = acd2f89b7af6cb3041d1e005dd8c3a81`
  * `post_stable_md5 = acd2f89b7af6cb3041d1e005dd8c3a81`
  * **BYTE_IDENTICAL: True** ✓
- Full-feed md5 diverges only because ONE new job (`f8b84968-e9f4-4418-b88d-cbc572e8e467`) was ingested by the discovery scheduler between the two snapshots — 0 pre-only excluded ids, 0 pre/post passing symdiff. The delta is a real discovery ingest, not a scoring change.
- **Perf smoke (fixture-ead@ against preview, backend under uvicorn --reload dev mode):**
  * cold response cache + cold scored cache (first call this reload): 1.91 s
  * response-cache hit (60 s TTL): 0.65 s / 0.77 s
  * response-cache MISS with warm scored cache (sort=nearest → sort=velocity → sort=best_fit): 1.49 s / 1.40 s / 0.80 s
  * Pre-unfreeze baseline was frontend Playwright LCP 3.98 s (Phase 0 closeout note); the scorer loop is now off the hot path for warm scored-cache reads. **Dev-mode caveat: preview runs `react-scripts start` + `uvicorn --reload`; production build + gunicorn workers will be materially faster.**
- Cache invariants (by construction, not tuning):
  * key includes `weights_version` → scoring semantics bump auto-invalidates
  * key includes `job.last_verified` iso → any job update auto-invalidates that job's row
  * key includes `ctx_signature` derived from prefs/eligibility/claims/apps/hidden → any user-state change auto-invalidates the user's rows
  * bounded LRU (500k default) → evicts oldest on overflow, never unbounded

### Step (iii) — Feed LCP re-measure · LANDED 2026-08-06T~13:25Z (dev-mode) · 2026-08-06T~14:15Z (prod-build one-off)

Two independent measurements — dev-mode and production-build — reported side-by-side without extrapolation:

**Dev-mode (preview `react-scripts start` + `uvicorn --reload`, authenticated /feed as fixture-ead@):**
- Probe: `backend/tools/feed_lcp_probe.py` — Playwright headless, 3 runs against `${REACT_APP_BACKEND_URL}/feed`. Artifact: `docs/phase-1-artifacts/feed_lcp_post_unfreeze.json`.
- **LCP median: 692 ms · min: 636 ms · max: 740 ms** (Phase 0 closeout LCP was **3.98 s**; the scorer-unfreeze removes the biggest chunk by keeping the 22k-job gate+score loop off the hot path via `services/scored_cache.py`).
- Supporting nav timings: TTFB ~103–130 ms · DOMContentLoaded ~332–364 ms · load event ~332–364 ms · wall-time-to-networkidle 22–23 s (long-tail widget XHR polling, NOT LCP).

**Production-build one-off (CRA `yarn build` → `npx serve -s build -l 4173`, torn down after measurement):**
- Probe: `backend/tools/prod_lcp_probe.py`. Artifact: `docs/phase-1-artifacts/feed_lcp_prod_build.json`.
- Bundle sizes on disk: `main.3931d382.js = 276K` · `main.6d316e3f.css = 52K`.
- **LCP median: 276 ms · min: 224 ms · max: 444 ms** — TTFB 3-5 ms (localhost) · DCL 32-35 ms · load 32-35 ms · wall 0.73-1.0 s.
- **Honest caveat #1:** cookies from the preview backend origin (`lynk-preview-2.preview.emergentagent.com`) do NOT transfer to `127.0.0.1:4173` (cross-origin). So the prod-build `/feed` render likely resolved to the auth-gated shell (login redirect) rather than the fully-authenticated feed body. Direct apples-to-apples measurement on an authenticated `/feed` under prod-build would need a proxy layer that this cycle deliberately doesn't build.
- **Honest caveat #2:** localhost TTFB is unrealistically low (no network). A real production hop adds ~50-100 ms.
- Static server was **torn down** post-measurement (`pkill -f 'serve.*4173'` verified; `curl http://127.0.0.1:4173/ → 000`). Dev servers untouched.

**Side-by-side (with caveats above):**

| Metric | Dev-mode /feed (authenticated) | Prod-build /feed (shell-only, x-origin cookies) |
|---|---|---|
| LCP median | 692 ms | 276 ms |
| LCP min | 636 ms | 224 ms |
| TTFB | 103-130 ms | 3-5 ms (localhost) |
| DCL | 332-364 ms | 32-35 ms |

Never extrapolated. Prod-build number is a shell-load reference point, not a claim about authenticated feed perf.

### Step (iv) — 1a Speed-ranked feed sort · LANDED 2026-08-06T~13:35Z
- New sort option `GET /api/v1/jobs/feed?sort=speed` — additive; `best_fit` remains default (per founder rail Q2 addendum). Existing sorts (`nearest`, `velocity`/`soonest_money`) untouched.
- Rank key: `(has_data ∈ {0,1}, median_days_to_response ↑, -score)` — employers with response data first, sorted ascending by median; no-data employers sink to the end and are labeled verbatim `"no response data yet"`.
- Data source: `services/outcome_autopilot.compute_group_stats(user_id, since_days=90, group_by='employer')`. **User-scoped** — the aggregate is over THIS USER's own `application_outcomes` only. No cross-employer response-history sharing (privacy hard-stop preserved).
- Employer key resolution: `job.canonical_key.split('::')[0]` (identical to `_load_application_meta` fallback in `outcome_autopilot._load_application_meta` line 92 — same key on both sides so match rate is by construction, not heuristic).
- Response payload: each passing card grows a `speed` block ONLY under `sort=speed`:
  ```
  "speed": { "median_days_to_response": 3.0 | null,
              "sample_size": <int>, "responded_count": <int>,
              "note": "no response data yet" | "median 3.0d to response · 3/4 responded" }
  ```
  Under other sorts the block is not injected — payload byte-shape for `best_fit` / `nearest` / `velocity` is unchanged.
- Focused test suite `backend/tests/test_phase1_speed_sort.py`: **5 passed** — sort-key data-first ordering, no-data bucket score-ordering, note copy for no-data + has-data, empty compute returns `{}`, and end-to-end insert-outcome → compute → assert median 3.0d + response_rate 1.0.
### Step (v) — 1b Apply Wave + Spectrum Builder · LANDED 2026-08-06T~13:45Z
- New module: `backend/domains/wave/__init__.py`. Endpoints:
  * `POST /api/v1/wave/authorize` — consent-gated on `submit_applications`. Body: `WaveScope{lane, within_mi, family, cap=25, standing_wave=false}`. One-shot batch that (i) enumerates candidates matching scope, (ii) filters to 3-hard-gate passers via `gate_engine.evaluate`, (iii) skips duplicates via `ctx.existing_applications`, (iv) respects the **rolling 30-day per-employer cap** (via `services/employer_cap`), counting wave-queued jobs against remaining slots so the wave itself cannot bypass cap, (v) shortlists via `applications.service.shortlist` (same code path as manual single-shortlist so DuplicateKey / EmployerCapReached exceptions surface identically), (vi) writes a single `wave_authorizations` row with consent-scope snapshot.
  * `GET  /api/v1/wave/authorizations` — most-recent-first list (limit 50).
  * `GET  /api/v1/wave/standing` — return active Standing Wave scope, if any.
  * `DELETE /api/v1/wave/standing` — idempotent deactivate.
- **Standing Wave**: when `scope.standing_wave=true`, the scope is upserted into `standing_waves` (unique by user_id, active=true). `services/wave.run_standing_waves_after_aab_tick(new_job_ids)` is the hook AAB ticks can call — re-runs the scope against JUST the new arrivals and queues, with cap enforced identically. (Wiring into `services/apply_at_birth.tick` is deliberately deferred to a follow-on cycle since the AAB scheduler flag is founder-gated; the hook is safe to call and unit-locked.)
- **Consent snapshot** (`_snapshot_consents`): reads `consent_records` for the user at authorize time; stored on the wave_authorizations row so audit can reconstruct what was granted at click time.
- **Cap NEVER bypassed proof** — focused test `test_wave_enumerate_respects_employer_cap` inserts 5 jobs @ single employer + 2 existing open apps and asserts wave enumerates AT MOST 1 additional (3-per-30d - 2 existing = 1 slot); `blocked_cap>=2`. Also live smoke as `fixture-ead@` against 15 SampleCo jobs (all one employer, cap=3, 1 existing assisted): wave queued **2** applications (correct), `wave_authorizations` row persisted with `queued_count=2` and `standing_wave=true`.
- Live smoke also confirmed `GET /wave/standing` returns the stored scope row with active=true.

### Step (vi) — 1c Instant-scheduling link · LANDED 2026-08-06T~13:50Z
- New persisted field on user preferences: `PreferencesPayload.booking_url: str | None`. Validator asserts non-empty values start with `https://` and pass `HttpUrl` shape (see `backend/domains/preferences/models.py::_validate_https`). Rejection surfaces as clean 422 with message `"booking_url must be an https:// URL"` (pre-existing validation-error handler bug in `server.py::scrub_validation_error` fixed in the same edit — pydantic v2 stuffs the raw ValueError into `ctx.error`, which was breaking `json.dumps`; handler now coerces `ctx` values to strings).
- Injection point: `backend/domains/email_route/__init__.py::_load_booking_url` reads the user's most-recent preferences payload. In `dispatch`, AFTER pre-flight passes (so claim-grounding is not muddied by user-supplied contact metadata), the body is appended verbatim as `\n\nBook a time: <url>`. Outbox row records `booking_url_attached: true`. Never invents placement — no injection unless the user has explicitly saved the URL.
- Live smoke as `fixture-ead@`: `POST /preferences` with `booking_url=https://calendly.com/fixture-user` → 201, version 2 persisted. `POST /preferences` with `booking_url=http://insecure.com/x` → 422 with clean error copy. HttpUrl validation stays server-side.

### Step (vii) — 1d Follow-up drafts · LANDED 2026-08-06T~13:55Z
- New module: `backend/domains/follow_ups/__init__.py`, new collection `follow_up_drafts`. Endpoints:
  * `POST /api/v1/follow-ups` — draft one follow-up for one application. Scheduling: if the user has an observed employer median-days-to-response, `scheduled_for = submitted_at + median_days`; else fallback = submitted_at + 7d. Body pre-built with per-tone prelude (warm/concise/inquisitive) and optional `custom_note`. Records `median_days_source` (`employer` or `fallback_7d`) for audit.
  * `GET  /api/v1/follow-ups[?state=draft|approved_and_dispatched|discarded]` — list drafts.
  * `POST /api/v1/follow-ups/{id}/approve` — the ONLY code path that transitions a draft toward send. Creates a **fresh `email_outbox` row** via `email_route.dispatch(...)` (which itself runs pre-flight validator + dedup + throttle + stores receipt, all under the existing `submit_applications` consent gate). Draft moves to `state=approved_and_dispatched` with `email_outbox_id` pointer. Non-draft states → 409 `follow_up_not_in_draft_state`.
  * `POST /api/v1/follow-ups/{id}/discard` — idempotent state transition to `discarded`.
- **HARD INVARIANT (test-locked):** `test_no_dispatch_sweep_touches_drafts` — grep-based static invariant that fails if ANY file outside `domains/follow_ups/` performs a WRITE op (`insert_one` / `update_one` / `delete_*` / `bulk_write` / `find_one_and_*`) on `follow_up_drafts`. Currently PASSING — no such write exists. If a future sweep is added it will break this test loudly.
- Focused tests: 9 pass (speed-sort 5, wave enumerate 1, follow-up scheduling 2, static hard-invariant 1) · 3 skipped due to a motor 3.5.1 + pytest-asyncio 1.4.0 executor-state incompatibility that produces "Event loop is closed" on 2nd+ async fixture-scoped Motor client per module. The three skipped locks (`wave_authorization_persists_consent_snapshot`, `approve_creates_fresh_outbox_row_and_marks_draft`, `approve_refuses_non_draft_state`) are each proven verbatim by live curl smoke:
  * `_snapshot_consents` verified live — the wave-authorize response returns `"consents_snapshot": {"process_career_data":"granted", "submit_applications":"granted", …}` for fixture-ead@.
  * approve→fresh outbox verified live — approve of a draft for fixture-ead@ passes through `email_route.dispatch` (same preflight+dedup+throttle path); a fresh outbox row is inserted and the draft is marked `approved_and_dispatched`.
  * approve refuses non-draft — verified live: `POST /follow-ups/{discarded_id}/approve` returns **409** `{"error":"follow_up_not_in_draft_state","current_state":"discarded"}` (raw payload copied into evidence).

### Step (v-preview) — Wave Preview endpoint · LANDED 2026-08-06T~14:00Z
- New route: `GET /api/v1/wave/preview?lane=&within_mi=&family=&cap=25` — consent-gated on `submit_applications` (identical to `/authorize` so the preview surface has zero privilege over the confirm surface).
- Runs `_enumerate_eligible` in dry mode. Returns `eligible_count`, `eligible_job_ids`, `eligible_summary` (id/title/company_name/canonical_key), full `breakdown` (`total_scanned`, `blocked_scope`, `blocked_hard_gate`, `blocked_cap`, `blocked_duplicate`), plus the interpreted scope echo and a `note: "read-only preview; nothing has been queued or authorized."`.
- Read-only proof: live smoke as `fixture-ead@` — `GET /wave/preview?cap=10` returned `eligible_count=2`, `breakdown.blocked_hard_gate=22436, blocked_cap=7`; **`GET /wave/authorizations` count remained at 1** (unchanged from the earlier authorize call) → preview writes nothing to `wave_authorizations` or `applications`.

### Step (v-aab) — Standing Wave wired into apply-at-birth ingest · LANDED 2026-08-06T~14:20Z
- Wiring in `backend/domains/discovery/service.py::refresh_all` — after each refresh completes and after the lifecycle-sweep runs, the newly-INSERTED job IDs (collected in `inserted_ids: list[str]`) are passed to `wave.run_standing_waves_after_aab_tick`. Every user with an active Standing Wave has their scope re-run over JUST the new arrivals, with cap enforced identically to the manual authorize path. The refresh summary now reports `standing_wave_auto_queue: {new_arrivals, users_processed, queued_total, error}`. Failure inside the hook is caught and logged — refresh_all NEVER fails because of Standing Wave.
- Focused test `backend/tests/test_phase1_standing_wave_tick.py::test_standing_wave_tick_full_flow` — 3-user fake-DB scenario:
  * User A (active Standing Wave, cap has room) → **queued 1** application; `wave_authorizations` row written with `triggered_by=standing_wave_aab_tick`, `queued_count=1`, `consents_snapshot.submit_applications=granted`.
  * User B (active Standing Wave, cap FULL at Acme — 3 existing open apps) → **queued 0**; `wave_authorizations` row still written for audit with `queued_count=0` and `breakdown.blocked_cap >= 1` (NAMED reason).
  * User C (`active=False`) → **skipped** — no wave_authorizations row for them.
  * Test passes in isolation and in the full ordered suite. Uses fully-mocked DB + `gate_engine` + `cap_svc` for hermetic execution.

### Step (§iv-vii frontend) — 1a/1b/1c/1d E2E surfaces on Fynd Liquid · LANDED 2026-08-06T~14:10Z
Playwright E2E smoke against `${REACT_APP_BACKEND_URL}` as `fixture-ead@`:
- **1a Speed sort toggle** (`frontend/src/pages/Feed.jsx`): `<SortSelector>` now includes `speed` option (data-testid=`feed-sort-select`). New `<SpeedChip>` component renders on every passing card only when `sort=speed`. Live smoke observed values: sort options `['best_fit','nearest','velocity','speed']`; after selecting speed → **9 speed chips visible, first chip text = `"no response data yet"`** (honest empty-state label; fixture-ead@ has no outcomes yet).
- **1b Apply Wave dialog** (`frontend/src/components/ApplyWaveCapsule.jsx`): capsule renders at `data-testid=apply-wave-capsule` above the feed grid. Opening it fires `GET /wave/preview`; the confirm button (`data-testid=apply-wave-confirm`) is DISABLED until preview loads AND eligible_count > 0. Live smoke: preview rendered breakdown_cap=7, breakdown_hard=22439, eligible list visible. `apply-wave-standing-toggle` present for Standing Wave opt-in; success state at `apply-wave-success`; consent-revoked state at `apply-wave-consent-required`.
- **1c Booking URL row** (`frontend/src/pages/Preferences.jsx`): new `<Card>` at `data-testid=preferences-booking-url` with `preferences-booking-url-input`. Save flow catches pydantic-shaped 422s with `loc.includes('booking_url')` and surfaces the honest server message (e.g. "Booking URL: booking_url must be an https:// URL"). Live smoke: row present.
- **1d Follow-up review lane** (`frontend/src/pages/FollowUps.jsx`, route `/follow-ups`): new page under `data-testid=follow-ups-page`. Filter tabs (draft/approved/discarded) at `follow-ups-filter-{state}`. Draft rows expose `follow-up-draft-row` + body preview + median-source label. Approve dialog `follow-up-approve-dialog` REQUIRES explicit destination + subject before confirm enables — no auto-send code path. Success creates a FRESH email_outbox row via `email_route.dispatch` (dry-run). Consent-revoked → `follow-ups-consent-required`. Empty state → `follow-ups-empty`. Sidebar link added at `data-testid=sidenav-link-follow-ups`.
- Frontend compiled cleanly (`webpack compiled with 1 warning` — an unused `AlertTriangle` import that was subsequently removed). Backend hot-reload picked up all changes. Full frontend E2E smoke script output: `ALL_OK`.

## §2 — Cycle close: full pytest vs 62 baseline (Phase 0 §14.1)

Same ordered run as Phase 0 §14.1, plus the three new Phase-1 test files:

```
python3 -m pytest \
   tests/test_preflight_validator.py \
   tests/test_receipt_compound_index_regression.py \
   tests/test_consent_scope_enum_guard.py \
   tests/test_apply_at_birth.py \
   tests/test_form_map_cache.py \
   tests/test_outcome_autopilot.py \
   tests/test_self_healing.py \
   tests/test_outcomes_endpoints.py \
   tests/test_surprise_me.py \
   tests/test_phase1_speed_sort.py \
   tests/test_phase1_follow_ups.py \
   tests/test_phase1_standing_wave_tick.py
```

**Result (2026-08-06T14:25Z):**
```
72 passed, 3 skipped in 3.80s
```

- **Delta from 62 baseline: +10 pass, +3 skip (with live smoke evidence in §v/§vii above), 0 regressions.**
  * `test_phase1_speed_sort.py`: **5 passed**.
  * `test_phase1_follow_ups.py`: **4 passed, 3 skipped** (motor/pytest-asyncio; each locked behavior proven via live curl in §v/§vii).
  * `test_phase1_standing_wave_tick.py`: **1 passed** (three-user fake-DB scenario locking cap-respect + inactive skip + wave_authorizations audit).

- **Backend rebrand (§i) did not perturb any existing test.**
- **Scorer unfreeze (§ii) did not perturb any existing test** — byte-identical proof over stable job intersection is documented above and holds independent of the pytest run.
- Focused suite runtime moved from 3.42 s (Phase 0 §14.1) to 18.80 s — the extra ~15 s is `test_phase1_follow_ups.py::scratch_db` creating Motor clients per test + `_enumerate_eligible` scanning 22k+ live jobs when the DB is not fully monkey-patched by the fixture. This is TEST cost only; no production cost.


## §3 — Phase 1 Gate closeout (2026-08-06 T~23:45Z)

### §iv-fix — G3d (Data Integrity) — LANDED · 6 defective rows annotated (fixture-only)

**Root-cause line — bug class: schema drift.**
`domains/wave/_snapshot_consents` was addressing legacy field names
(`status` / `granted_at` / `revoked_at`) that never existed in the
Phase-6-hardened `consent_records` shape (`granted: bool` + `ts:
datetime`, written by `domains/consent/service.record` via
`repository.append`). Every projected value collapsed to falsy and the
returned dict fell through empty for every scope the user had actually
granted. A hardening pass elsewhere in the codebase did not sweep this
reader.

**Blast radius — observed values.**
- `wave_authorizations` count total: **18** (all-time, preview DB).
- Defective rows (pre-fix, `consents_snapshot == {}`): **6**.
- Defective rows per path: **3 × `user_batch`** + **3 × `standing_wave_aab_tick`** — both paths were affected.
- Distinct users involved: **1** (`c9f47fd8-fd59-4df9-8c9c-b7ff68fb4785` = **fixture-ead@opportunityos.dev**, a synthetic fixture rebased on every backend startup).
- Real users affected: **0** — preview environment has no real users. **The defective path WOULD have shipped absent this gate** — downstream privacy audits of "what did the user consent to at click time?" would have returned an empty dict on every affected row, silently breaking the invariant.
- Post-fix rows (from 2026-08-06T14:19Z onwards, commit `903af9e4`): **12 / 12 rows** carry the full 6-scope snapshot (`discover_jobs`, `email_me`, `generate_materials`, `process_career_data`, `submit_applications`, `track_applications` — all `"granted"`).

**Annotation trail — immutable, append-only.**
Migration `backend/tools/phase1_g3d_annotate_wave_snapshots.py` attached
a `consents_snapshot_correction` sub-document to each of the 6
defective rows. Shape (verbatim):

```json
{
  "original": {},
  "corrected": {"discover_jobs": "granted", "email_me": "granted",
                "generate_materials": "granted", "process_career_data": "granted",
                "submit_applications": "granted", "track_applications": "granted"},
  "corrected_source": "fixture_invariant_fallback (historical consent_records cycled out by seed rebases; fixture invariant is all-6-granted)",
  "corrected_at": "2026-08-06T23:44:35.322119+00:00",
  "reason": "phase-1-g3d-fix: `_snapshot_consents` reader in `domains/wave/__init__.py` was addressing legacy field names (...)",
  "source": "phase1_g3d_annotate_wave_snapshots"
}
```

Invariants (test-locked in `tests/test_phase1_g3d_annotation_trail.py`):
- **Never rewritten silently** — the row's top-level `consents_snapshot`
  keeps its original value verbatim (`{}` on all 6 rows). Only a NEW
  field `consents_snapshot_correction` is added. **This is the deliberate
  audit-honest choice — a silent rewrite of the top-level field would
  destroy the historical evidence of the defect. Founder accepted this
  design at the Phase 1 gate PASS (2026-08-06).** Enforced by
  `test_annotation_never_rewrites_original`.
- **Idempotent** — re-running the migration is a no-op on already-annotated
  rows. Enforced by `test_annotation_migration_is_idempotent` (`s2.annotated_now == 0`).
- **Queryable** — a sparse index on `consents_snapshot_correction.corrected_at`
  exists on `wave_authorizations`. Enforced by `test_correction_index_exists`.
- **Honest point-in-time gap** — for the 6 affected rows the `corrected`
  value comes from the `fixture_invariant_fallback` (fixture user, all
  scopes granted invariant) because the historical `consent_records`
  rows those wave authorizations were based on have since been wiped by
  subsequent seed rebases. The migration NEVER fabricates a snapshot
  for a non-fixture user — for those it records `no_data_recoverable`.

Migration summary artifact: `/app/docs/phase-1-artifacts/g3d_annotation_summary.json`.
Frozen post-migration audit dump: `/app/docs/phase-1-artifacts/g3d_annotated_rows_frozen.json`.

**Dual-path regression tests — post-fix schema locked.**
New `tests/test_phase1_wave_consent_snapshot.py` — 4 passed:
- `test_snapshot_mirrors_granted_bool_directly` — unit-level `_snapshot_consents` against correct-schema fixture rows; asserts `snapshot != {}` and `latest-per-scope` semantics via revoke→regrant sequence.
- `test_user_batch_path_writes_correct_snapshot` — `authorize_wave` code path composed via `_snapshot_consents` + `_persist_authorization`; asserts `triggered_by=="user_batch"` and `stored != {}`.
- `test_standing_wave_aab_tick_path_writes_correct_snapshot` — `run_standing_waves_after_aab_tick` end-to-end with stubbed enumeration; asserts `triggered_by=="standing_wave_aab_tick"` and `stored != {}`. **This is the direct anti-regression for the empty-snapshot bug on the standing-wave path.**
- `test_snapshot_rejects_legacy_field_addressing_schema` — defensive fallback exercises the `granted_at` legacy branch to prove it still yields `"granted"` for a row with only legacy fields.

### §v-fix — G1d (Data Gap) — LANDED · differential `sort=speed` observable

**Fix.** Added a second SAMPLE employer (`ResponsiveDemo (fixture)` at
`responsivedemo.demo`) with **2 sample jobs passing gates for fixture-ead@**
(vehicle systems Phoenix, HIL simulation Remote US — both offer
sponsorship, comp ≥ 90k). Seeded 3 historical applications to that
employer for the fixture user with response outcomes at deltas 3.0d /
4.0d / 5.0d → **median 4.0d, 3/3 responded**.

**Observed differential ordering (`GET /api/v1/jobs/feed?sort=speed`
as fixture-ead@):**
```
[1] ResponsiveDemo (fixture)  · median=4.0  · resp=3/3  · note="median 4.0d to response · 3/3 responded"
[2] ResponsiveDemo (fixture)  · median=4.0  · resp=3/3  · note="median 4.0d to response · 3/3 responded"
[3] SampleCo (demo)           · median=None · resp=0/0  · note="no response data yet"
[4-11] SampleCo (demo)        · median=None · resp=0/0  · note="no response data yet"
```

Rank key `(has_data ∈ {0,1}, median_days_to_response ↑, -score)` holds:
data-bearing employers rise to the top; no-data employers sink to end
with the honest "no response data yet" label. Verified via curl
assertion (`DIFFERENTIAL_ORDER_OK ✓`) at 2026-08-06T~23:45Z.

### §browser-leg-replay — G7-G10 (Playwright evidence) — LANDED

Committed self-contained script: `/app/docs/phase-1-screenshots/g7_g10_evidence.py`.
Result JSON: `/app/docs/phase-1-screenshots/g7_g10_results.json` (**all_passed=true**).

| Gate | Name | Observed | Passed |
|---|---|---|---|
| G7 | speed-sort toggle + honest labels | `sort_options=[best_fit, nearest, velocity, speed]`, `speed_chip_count=11`, first two chips `"4d median · 3/3"` (ResponsiveDemo), next four `"no response data yet"` (SampleCo). `has_data_label=true` **and** `has_no_data_label=true`. | ✅ |
| G8 | Wave preview → confirm invariant | `apply-wave-capsule` present, opening fires `GET /wave/preview`, `apply-wave-confirm` count BEFORE open = `0`, preview breakdown rendered (`hard_gate=22487`, `cap=7`, `scope=0`, `duplicate=0`), 4 eligible rows visible, confirm surfaces AFTER preview loads. | ✅ |
| G9 | booking URL row round-trip + inline http:// rejection | `preferences-booking-url` + `preferences-booking-url-input` present, `https://…` value round-trips across reload, `http://…` yields server-side 422 with copy `"must be an https:// URL"`. | ✅ |
| G10 | follow-up review lane · never-auto-sent | `follow-ups-heading="Follow-up drafts"`, page copy contains `"never auto-sent"`, filter tabs rendered. Draft-row count is 0 in the current fixture state (empty state is a legitimate outcome; script cancels the approve dialog even when opened — never confirms). | ✅ |

Screenshots at `/app/docs/phase-1-screenshots/g7_feed_default.jpeg`,
`g7_feed_sort_speed.jpeg`, `g8_wave_preview_open.jpeg`,
`g9_booking_saved_https.jpeg`, `g9_booking_http_rejected.jpeg`,
`g10_follow_ups.jpeg`.

Script UI-login uses fixture-ead@ credentials from
`/app/memory/test_credentials.md`; recovers from dev-mode 502s via
`_goto_stable(url, max_attempts=6)`; retries whole login up to 3× to
survive frontend hot-reload restarts. Rails held: script never calls
`/wave/authorize` (only `/wave/preview` via UI open), never confirms a
follow-up approve dialog (only opens + cancels).

### §4 — Cycle close: full pytest vs 72p/3s baseline

Same ordered command as §2 plus the 2 new Fix-1 files:

```
python3 -m pytest \
   tests/test_preflight_validator.py \
   tests/test_receipt_compound_index_regression.py \
   tests/test_consent_scope_enum_guard.py \
   tests/test_apply_at_birth.py \
   tests/test_form_map_cache.py \
   tests/test_outcome_autopilot.py \
   tests/test_self_healing.py \
   tests/test_outcomes_endpoints.py \
   tests/test_surprise_me.py \
   tests/test_phase1_speed_sort.py \
   tests/test_phase1_follow_ups.py \
   tests/test_phase1_standing_wave_tick.py \
   tests/test_phase1_wave_consent_snapshot.py \
   tests/test_phase1_g3d_annotation_trail.py
```

**Result (2026-08-06T~23:47Z):**
```
79 passed, 3 skipped in 3.74s
```

- **Delta from 72p/3s baseline: +7 pass, 0 regressions.**
  * `test_phase1_wave_consent_snapshot.py`: **4 passed** (dual-path + unit + defensive fallback).
  * `test_phase1_g3d_annotation_trail.py`: **3 passed** (immutability + idempotency + queryability index).
- Skipped tests unchanged (motor/pytest-asyncio; each locked behavior proven via live curl in §v/§vii).

### §5 — Ready for founder replay

**All Phase 1 gate work committed. Rails held throughout: preview only,
consent-gated everything, cap NEVER bypassed, no merge/push/deploy, no
real submissions, follow-ups never auto-sent, browser-leg script never
calls authorize or confirms approve.**

Founder replay targets:
- `/app/docs/phase-1-screenshots/g7_g10_evidence.py` (committed script)
- `/app/docs/phase-1-screenshots/g7_g10_results.json` (committed JSON) + screenshots
- `/app/docs/phase-1-artifacts/g3d_annotation_summary.json` + `g3d_annotated_rows_frozen.json`
- Curl re-checks:
  - `GET /api/v1/jobs/feed?sort=speed` — ResponsiveDemo (fixture) positions [0,1], SampleCo positions [2..10]
  - `GET /api/v1/wave/authorizations` — every post-fix row carries a 6-scope non-empty `consents_snapshot`; every pre-fix row carries a `consents_snapshot_correction` sub-document

### §6 — Phase 1 gate VERDICT: PASS (2026-08-06, founder-attested)

Triple-source independent replay outcome (founder's tester run, curl re-checks, script replay):

- **G3d re-check: PASS.** Fresh authorize writes all-granted snapshot mirroring live consents; 13 recent rows correct; the 6 historical rows carry the immutable annotation. Founder explicitly accepted the audit-honest choice of leaving the top-level defective value intact and carrying the correction in the annotation blob.
- **G1d re-check: PASS on a clean rebased fixture.** ResponsiveDemo at positions 1-2 with `median 4.0d · 3/3`, SampleCo below with `"no response data yet"`. The earlier transient FAIL was tester-contamination via `/wave/authorize` calls that queued apps to ResponsiveDemo; dedup correctly excluded them — dedup working as designed, noted in gate record.
- **G7-G10 replay: 6/6 substantive keys MATCH.** The single `hard_gate 22487→22486` delta ruled EXPECTED-VOLATILE (live job-count drift from staleness sweep); every gate boolean reproduced exactly.
- **Full gate tally:** G1-G10 all PASS. Both fixes verified independently. Pytest **79p/3s** (+7 pass vs 72p/3s, 0 regressions).

Phase 2 auto-opens per the master directive.
