# ATLAS-STATE.md — running state of the FYND ATLAS program

**Persisted per FYND-ATLAS §47.** Records the current gate position, orchestrator/founder decisions, and burn-down of the standing ordered sequence. Every logical unit lands here as it commits.

---

## §1 · Current gate position (2026-08-13)

- **Hotfix trio + Gate Fix** — GATE-PASSED on `main` @ `c00b7737` + `e49406d6` + `6e600014` + `06149bf0`. Waiting on founder's Save-to-GitHub + Re-publish click; workspace-side ready.
- **Save-to-GitHub sync** — hygiene sweep complete, `.env.example` schemas written, 4 branches TRIPWIRE_CLEAN, push credential-blocked (founder rail). `main` HEAD prior to P0 kickoff: `06149bf0`.
- **P0 TRUTH AUDIT** — **UNBLOCKED** by orchestrator decide-and-document decision (2026-08-13). Founder deferred the Re-publish click "for now". Decision recorded verbatim below.

## §2 · Decide-and-document — P0 unblock (2026-08-13, orchestrator)

**Decision.** P0 Truth Audit begins immediately on `main`. Every commit leaves the app continuously releasable.

**Rationale (verbatim from orchestrator).**
> "P0 work happens in the workspace on main and cannot affect prod until the founder's Re-publish click, which remains the founder's alone; waiting idle serves no rail. The hotfix trio (c00b7737) stays gate-passed on main and will ship together with P0 truth items whenever the founder clicks Re-publish."

**Rails held.**
- Continuous releasability: `main` stays green after every commit; supervisor hot-reload works throughout; no partial migrations.
- Publish clicks remain the founder's alone. No merge to origin, no deploy, no `.env` edits.
- SAMPLE / fixture rows NEVER surface in the P0 metrics that will render on `/standards`. `is_sample=False` filter is a hard invariant on every counted read.
- Never-fabricate: when `n` is below the honest threshold, render "measuring" — never a synthesized number.
- `country_allowlist` schema addition remains QUEUED for P1. Not pulled forward.

## §3 · P0 TRUTH AUDIT — full scope (9 items)

Ordered by dependency, not by founder-list letter. Each item ships as its own commit with tests alongside.

| # | Founder letter | Item | Status | Commit |
|---|---|---|---|---|
| 1 | init | Initialize ATLAS-STATE.md | **DONE** | `b7b8979a` |
| 2 | (b) | Brand sweep — kill `opportunityos.dev` from every user-facing served surface | **DONE** | `41a29043` |
| 3 | (a) | `/privacy-policy` serves the real static crawlable versioned policy (no SPA shell) | **DONE** | `8249bd73` |
| 4 | (c) | Footer version string derives from build (`package.json`), no `v0.1` literal | **DONE** | (chained) |
| 5 | (g) | `robots.txt` + `sitemap.xml` as real static files, correct content-types | **DONE** | (chained) |
| 6 | (e) | Operator / about page (legal entity, contact) | **DONE** | (chained) |
| 7 | (d) | `/standards` sync — reflect Phase 0-6 + hotfix, add change history | **DONE** | (chained) |
| 8 | (f) | `/standards` outcome rows (median days-to-first-response, interviews/100 apps) + public claim-verification ladder | **DONE** | (chained) |
| 9 | (i) | `/standards` per-country coverage row — real rows only, SAMPLE segregated, indeterminate bucket | **DONE** | (chained) |
| 10 | (h) | North-star instrumentation — TQI + guardrails; measure baseline BEFORE optimization; SAMPLE excluded | **DONE** | (chained) |
| 11 | evidence | `docs/P0-TRUTH-EVIDENCE.md` + tripwire + STOP for split-brief gate | **DONE** | (this commit) |

## §4 · Never-fabricate honest thresholds

Recorded so every P0 render obeys the same rule:

- **Median days-to-first-response.** Render only when the pool has ≥20 real (non-SAMPLE, non-fixture) `application_outcomes` rows tagged `event=response_received`. Below threshold → `"measuring"` string.
- **Interviews per 100 applications.** Render only when the pool has ≥50 real submitted applications. Below threshold → `"measuring"`.
- **Per-employer response medians on the /employers pool page** (queued, P4/P5) — never render below n=5 for a given employer; below → the employer row shows `"measuring"` and the number is omitted.
- **Time to Qualified Interview (baseline).** Render current pool baseline when ≥10 real interview outcomes exist; below → `"measuring (baseline)"`.
- **Guardrail metrics** (application→response, response→interview, false-pass, false-exclusion, duplicate rate, closed-listing exposure, consent-violation count). Render current pool baseline when ≥30 real applications exist; below → `"measuring (baseline)"` with the honest n shown.

## §5 · Sample / fixture segregation (hard invariant)

Every P0-produced metric that renders on `/standards` MUST filter `is_sample=False` at the DB level (or exclude fixture user IDs `fixture-ead@opportunityos.dev`, `fixture-broad@opportunityos.dev`, `fixture-employer-member@opportunityos.dev`, `admin@opportunityos.dev`, `support@opportunityos.dev` from user-scoped queries). Static tests (below) fail CI if a metrics function reads a row without the exclusion.

## §6 · P0 tests (built alongside each item)

- `backend/tests/test_standards_metrics_exclude_sample.py` — hard-locks every metrics accessor excludes SAMPLE rows.
- `backend/tests/test_standards_change_history.py` — locks phase sync + change history append-only shape.
- `backend/tests/test_public_static_assets.py` — `curl /robots.txt` returns text/plain and mentions Fynd; `curl /sitemap.xml` returns application/xml; `curl /privacy.html` returns text/html and is Version 1.0.
- `backend/tests/test_version_endpoint.py` — `/api/v1/meta/version` returns semver derived from `package.json`/`requirements`, NOT a literal `v0.1`.

## §7 · Not in this P0 (parked)

- `country_allowlist` schema addition to `eligibility_requirements` — QUEUED for P1 Foundation. Do not pull forward.
- Real per-employer response medians — needs the outcomes pool to hit n=5 per employer, queued for P4/P5.
- P1 Foundation items (13 per `ATLAS-FEATURE-MAP.md`) — do NOT start until founder split-brief gate on this P0.

---

## §8 · Timeline (append-only)

- **2026-08-13T13:00Z** — ATLAS-STATE.md initialized. P0 Truth Audit unblocked by orchestrator decide-and-document. Founder's Re-publish click remains outstanding.
- **2026-08-13T13:45Z** — P0 Truth Audit COMPLETE (items a-i + init + evidence). All 11 sequence items landed on `main` under continuous-releasability discipline. Evidence in `docs/P0-TRUTH-EVIDENCE.md`. 83 P0-focused tests passing. Tripwire clean. STOPPED for founder split-brief gate + Save-to-GitHub push + Re-publish. P1 Foundation remains BLOCKED.
