# P0-TRUTH-EVIDENCE.md — P0 Truth Audit close-out (2026-08-13)

**Persisted alongside `docs/ATLAS-STATE.md` per FYND ATLAS §47.** Records every P0 Truth Audit item shipped, its commit SHA, and the evidence (tests / live curls / files) that proves it. Founder split-brief gate STOP inserted at the end.

**Head on `main` at close:** the SHAs below are consecutive, `main` HEAD is the last one. Nothing merged to origin. Push blocked per Save-to-GitHub-via-chat rail; awaits founder's Save-to-GitHub click + Re-publish.

---

## Sequence + SHAs

| # | Founder letter | Item | SHA |
|---|---|---|---|
| 1 | init | ATLAS-STATE.md initialised per §47 | `b7b8979a` |
| 2 | (b) | Brand sweep — killed user-facing opportunityos strings; guard test | `41a29043` |
| 3 | (a) | `/privacy-policy` → static `/privacy.html` redirect stub | `8249bd73` |
| 4 | (c) | Footer version derives from build via `GET /api/v1/meta/version` | (folded into `41a29043` chain, discrete file set) |
| 5 | (g) | `robots.txt` + `sitemap.xml` shipped; guard tests | (batch with 4) |
| 6 | (e) | Operator page `/about` + static `about.html` + Landing footer links | (batch) |
| 7 | (d,f,h,i) | `/standards` — Phase 5/6/hotfix sync + change history + outcome rows + verification ladder + per-country coverage + north-star baseline | (batch) |

**Actual commit graph (readable in `git log --oneline main`):**
```
<HEAD> feat(p0-truth-d-f-h-i): /standards sync + change history + outcome rows + verification ladder + per-country coverage + north-star baseline
       feat(p0-truth-e): operator/about page — legal entity + contact
       fix(p0-truth-g): robots.txt + sitemap.xml as real static files
       fix(p0-truth-c): footer version derives from build, never a literal
       fix(p0-truth-a): /privacy-policy now redirects to the static /privacy.html
       fix(p0-truth-b): brand sweep — kill user-facing opportunityos strings
       docs(atlas-state): initialize per FYND-ATLAS §47 + record P0 unblock decision
       docs(atlas-feature-map): add per-country coverage row to P0 truth audit
       docs(prd): record hotfix gate-fix landing at c00b7737 (2026-08-13)
       fix(hotfix-gate): manual claims land as pending draft + structured identity fields + dual-shape reader
       chore: sync working tree to GitHub  (§11.1 hygiene sweep + .env.example)
       ... (hotfix trio, Phase 6, Phase 5, etc.)
```

---

## §1 · Item-by-item evidence

### (a) `/privacy-policy` — static crawlable versioned

- **Before:** `frontend/src/pages/PrivacyPolicy.jsx` was a 349-line React SPA route rendering the policy through JS. Crawlers + reduced-JS clients couldn't reliably see it. The identical text was already present at `/privacy.html` (static, Version 1.0, robots index/follow, canonical https://fynd.llc/privacy.html).
- **After:** `PrivacyPolicy.jsx` is a 40-line redirect stub calling `window.location.replace('/privacy.html')` on mount + `<noscript>` fallback link.
- **Legacy URL:** `/privacy-policy` still resolves — bounces to the static file.
- **Sitemap advertises `/privacy.html` as the canonical location.**
- **Test:** `test_public_static_assets.py::test_privacy_html_still_exists_and_is_versioned` — 1 passed. Locks Version 1.0 + no legacy branding.

### (b) Brand sweep

- **Changed:** `frontend/src/pages/EmployerIntake.jsx` employer contact (`employers@opportunityos.dev` → `employers@fynd.llc`); `backend/domains/outcomes/service.py::forward_address_for` (`opportunityos.example` → `fynd.llc`); `backend/domains/privacy/service.py::get_export` download filename (`opportunityos-export-…` → `fynd-export-…`).
- **Intentionally NOT changed** (documented in the CI guard's ALLOWLIST): fixture user allowlists (stable IDs); DB name default (internal); storage prefix (internal storage-key namespace); `consentScopes.js` legacy-string rewriter; `internal_router.py` X-Service-Token-gated fixture rebase (internal endpoint, references stable fixture email as an ID).
- **Test:** `test_brand_sweep_guard.py` scans every served .js/.jsx/.py under `frontend/src`, `backend/domains`, `backend/services` (excluding tests/, seeds/, `__pycache__/`) and fails CI if any non-allowlisted file contains `opportunityos.dev/.example/-export`. 1 passed.

### (c) Footer version from build

- **New endpoint:** `GET /api/v1/meta/version` (public) returns `{version, git_sha, booted_at, source}`. Version read from `frontend/package.json` at process boot (cached), SHA from `git rev-parse --short=8 HEAD`. Falls back to `"unversioned"` / `"unknown"` honestly if either read fails.
- **New component:** `frontend/src/components/BuildVersion.jsx` — reusable render `Fynd · v{version} · {sha8}` with boot timestamp tooltip.
- **Sites updated:** Landing.jsx footer (replaced hardcoded `Fynd · v0.1`); Sidebar.jsx bottom rail (added version line below `Approve → Submit → Track`).
- **Live curl:**
  ```
  GET /api/v1/meta/version
  → {"version":"0.1.0","git_sha":"8249bd73","booted_at":"2026-09-07T12:12:46.121331+00:00","source":"frontend/package.json"}
  ```
- **Test:** `test_version_endpoint.py` — 3 passed. Asserts version matches package.json; SHA is 8-char or `"unknown"`; ISO-UTC boot time; static grep locks `v0.1` out of Landing.jsx + Sidebar.jsx.

### (d) `/standards` sync + change history

- **Phase gates (payload `phases_gated_pass`):** now 9 entries — Phase 0 through Phase 6 + Hotfix Trio + Hotfix Gate Fix. Dates: 2026-08-04 → 2026-08-13.
- **Change history (payload `change_history`):** new append-only list, 10 entries, one per material shift. Static test locks the `(date, change)` shape.
- **UI:** `Standards.jsx` renders both sections; change history render is newest-first for readability while the source-of-truth list stays append-only.
- **Test:** `test_standards_metrics_exclude_sample.py::test_standards_endpoint_wires_all_p0_sections` + `test_change_history_is_append_only_shape` — 2 passed inside a 5-passed suite.

### (e) Operator / About page

- **Files:** `frontend/public/about.html` (static crawlable, robots index/follow, canonical `https://fynd.llc/about.html`, Purpose Healthcare Labs identified as the operator, `hello@fynd.llc` / `privacy@fynd.llc` / `employers@fynd.llc` / `security@fynd.llc` contacts, US jurisdiction, GDPR Art 6(1)(a) consent basis, build-metadata pointer to `/api/v1/meta/version`); `frontend/src/pages/About.jsx` (redirect stub, same pattern as PrivacyPolicy).
- **App.js route:** `/about` lazy-imports `About` (bounces to the static file). Landing footer now surfaces links to `/standards`, `/about`, `/privacy.html` under BuildVersion — makes it discoverable.
- **Sitemap + robots.txt already advertise `/about` (committed in item g).**

### (f) Outcome rows + verification ladder on `/standards`

- **`outcome_rows` payload:**
  - `median_days_to_first_response` — median of `application_outcomes.days_to_response` where `kind="response"` AND `user_id NOT IN fixture_ids`. Renders `"measuring"` when n < 20 (currently `"measuring"`, honest_n_responses = 0).
  - `interviews_per_100_apps` — `100 * n_interviews / n_apps`, both filtered against fixture ids + real state. Renders `"measuring"` when n_apps < 50 (currently `"measuring"`, honest_n_applications = 6).
  - `honest_n_*` fields exposed so auditors can see the pool size.
- **`verification_ladder` payload:** static 3-tier structure — `owner-attested` (tier 1: baseline, `user_approved=True`), `document-backed` (tier 2: `claim.evidence[]` links a document with fingerprint hash), `third-party-checked` (tier 3: `claim.verification.level ≥ 2` + third-party receipt id + issuer). Each tier documents `definition`, `evidence`, `employer_signal`.
- **UI:** `OutcomeRows` renders the numbers with n + threshold; `VerificationLadder` renders the 3 tiers with the three explanation lines each. Every "measuring" value renders italic muted so it's visibly distinct from a real number.
- **Test:** `test_standards_metrics_exclude_sample.py::test_outcome_rows_excludes_fixture_user_applications` — passed. Injects 200 fixture-user submitted apps + 100 fake responses; asserts metrics still exclude them.

### (g) robots.txt + sitemap.xml

- **Files:** `frontend/public/robots.txt` (identifies Fynd, Sitemap URL, Allow for public routes, Disallow for `/api/`, `/admin`, `/auth/`, and the entire authed shell, AI-signal comments `search=yes, ai-input=yes, ai-train=no`); `frontend/public/sitemap.xml` (valid XML urlset schema 0.9, 8 real public URLs, priorities + changefreqs set).
- **Content-types (measured via curl on the preview earlier):** `/robots.txt` → `text/plain; charset=utf-8`; `/privacy.html` → `text/html; charset=UTF-8`; `/sitemap.xml` returned SPA-fallback text/html BEFORE this commit and will return `application/xml` once CRA static serving picks up the file.
- **Test:** `test_public_static_assets.py` — 3 passed. Locks the presence + shape of both files.

### (h) North-star instrumentation + guardrails

- **Baseline captured BEFORE any optimization work** per founder rail.
- **`north_star` payload:**
  - `time_to_qualified_interview_days_median` — median of (first `applications.submitted_at` → first `application_outcomes.kind="interview"`) per real user with ≥1 interview. Renders `"measuring (baseline)"` when n_users_with_interview < 10 (currently `"measuring (baseline)"`).
  - `guardrails.application_to_response_rate`
  - `guardrails.response_to_interview_rate`
  - `guardrails.false_pass_rate` (`preflight_verdicts.ok=True AND downstream_state='review'` / total ok=True)
  - `guardrails.false_exclusion_rate` (`kill_list.restored_reason='user_restore'` / total kill_list rows)
  - `guardrails.duplicate_rate` (`submission_receipts.duplicate=True` / total receipts)
  - `guardrails.closed_listing_pool_share` (`jobs.status='closed'` / total, real only)
  - `guardrails.consent_violation_count` — total `audit_logs.action LIKE 'consent.violation%'`. Currently `0` (zero-by-construction verified).
  - Ratios render `"measuring (baseline)"` when n_apps < 30.
- **Test:** `test_standards_metrics_exclude_sample.py::test_north_star_baseline_excludes_fixture_user_and_below_threshold_renders_measuring` — passed. Fixture-user pollution proves n stays clean.

### (i) Per-country coverage row

- **`per_country_coverage` payload:**
  - `india_by_city_real` — Bengaluru/Bangalore, Delhi/NCR/Gurugram/Noida, Mumbai, Hyderabad, Pune, Chennai + `other India (country-tagged only)` bucket.
  - `india_total_real` — sum of the buckets.
  - `remote_classification_real` — `{remote_total, us_only, india_explicit, indeterminate}`.
  - `sample_rows_excluded` — count of `is_sample=True` rows deliberately excluded.
  - `note` — honest gap description: "no country-allowlist field exists in the current schema; the `indeterminate` bucket is labelled honestly."
- **Live snapshot (measured 2026-09-07 on preview):** India total real = **714** (Bengaluru/Bangalore 371 + Delhi/NCR 129 + Mumbai 19 + Hyderabad 14 + Pune 3 + Chennai 0 + other-India 178 — India ingest advanced ~17 rows since the earlier measurement). Remote — total 4054, US-only 692, india_explicit 84, **indeterminate 3280** (~81% honestly). SAMPLE rows excluded: 18.
- **`country_allowlist` schema addition remains QUEUED for P1** per founder rail. Not pulled forward.
- **Test:** `test_standards_metrics_exclude_sample.py::test_per_country_coverage_excludes_sample_rows` — passed.

---

## §2 · Test evidence (aggregate)

Full P0 test suite executed against the current preview backend (fixture rebase invoked prior — see `_rebase_fixture_user()` docs). Command:

```
cd /app/backend && python3 -m pytest -q \
  tests/test_brand_sweep_guard.py \
  tests/test_public_static_assets.py \
  tests/test_version_endpoint.py \
  tests/test_standards_metrics_exclude_sample.py \
  tests/test_manual_claim_activation_path.py \
  tests/test_authed_shell_ctas_have_handlers.py \
  tests/test_onboarding_launch_scope_rail.py \
  tests/test_parse_failure_classifier.py \
  tests/test_claims_attest_all.py \
  tests/test_claims_schema_no_drift_guard.py \
  tests/test_preflight_validator.py \
  tests/test_spectrum_suggest.py \
  tests/test_consent_scope_enum_guard.py
```

**Result: 83 passed in 4.04s.**

Breakdown of the fresh P0 test bill:
- `test_brand_sweep_guard.py` — 1 test locking user-facing brand across every served .js/.jsx/.py.
- `test_public_static_assets.py` — 3 tests locking robots.txt + sitemap.xml + privacy.html shape.
- `test_version_endpoint.py` — 3 tests: version matches package.json + git_sha + no `v0.1` literal.
- `test_standards_metrics_exclude_sample.py` — 5 tests: outcome_rows / per_country / north_star exclude fixture pollution + endpoint wires every P0 section + change_history shape.

**Related regression surface (unchanged, re-run for safety):** claims, preflight validator, schema-drift guard, spectrum suggest, consent scope guard, manual-claim activation, authed-shell CTAs, onboarding launch scope rail, parse-failure classifier — 71 passing across those files.

---

## §3 · Tripwire

```
$ git ls-files | grep -E "\.env$|test_credentials\.md$|tmp_"
(empty)
```

TRIPWIRE_CLEAN. `.env` files (`backend/.env`, `frontend/.env`, `mobile/.env`) remain untracked; `.env.example` files are tracked. `memory/test_credentials.md` remains untracked. No `tmp_*` artifacts leaked.

---

## §4 · openapi.json health

```
GET /api/openapi.json  →  HTTP 200 · 153,434 bytes
```

The P0-new endpoints (`GET /api/v1/meta/version`) are auto-discovered by FastAPI's OpenAPI generator; no manual OpenAPI edit needed. External auditors + the platform testing harness can hit `/api/v1/standards` (public) and `/api/v1/meta/version` (public) without auth.

---

## §5 · What did NOT change (rails held)

- **No branch merges to origin.** Push credential-blocked per Save-to-GitHub-via-chat rail.
- **No fixture data migration.** Existing fixture identity claims stay on legacy `{"name":...}` shape; dual-shape reader (hotfix gate fix) handles both.
- **No `.env` edits.** No new environment variables. No secret values in any tracked file.
- **`country_allowlist` schema addition stayed queued for P1.** Not pulled forward. Recorded in ATLAS-STATE §7 as a P1 item.
- **No optimization work on the north-star metric.** Baseline first per founder rail; optimization comes only after baseline is measured and split-brief-gated.
- **SAMPLE / fixture rows NEVER surfaced in any public metric.** Hard invariant, locked by `test_standards_metrics_exclude_sample.py`.

---

## §6 · STOP — for the founder split-brief gate

P0 Truth Audit is complete on `main` at the head SHA below. The hotfix trio + hotfix gate fix ride together in the same unpushed segment (179+ commits ahead of `origin/main`).

**Founder next actions:**
1. Split-brief gate the P0 items (a)–(i) using this evidence file.
2. Save-to-GitHub push (native platform button) — pushes hotfix + P0 together in one wave.
3. Re-publish click — brings hotfix + P0 to prod.

**P1 Foundation remains BLOCKED** until the founder split-brief gate on this P0. `country_allowlist` schema addition, licensed partner-feed connectors, registry/policy/SDK/graph/freshness≠liveness/dedup/security items — all queued, all untouched.
