# PHASE-5-EVIDENCE.md — Website Scaling Tier

**Authorized:** 2026-08-09 (founder brief · Phase 5).
**Regime:** no-questions decide-and-document · precision protocol · rails absolute.
**Baseline before Phase 5:** 114 passed / 3 skipped (Phase 0-4 tester-leg PASS closeout at SHA `b87d9c14`).

Evidence lands as items close.

---

## 5a · RESUME-FREE APPLY / PASSPORT SHARE LINK — **LANDED**

**Decide-and-document:**

- **Consent scope added:** `share_passport` (`core/policy.py`). Non-required, revocable.
- **URL shape:** `/api/v1/share/p/{share_id}?t={sig}`. HMAC-SHA256 over `share_id|user_id|scope|expires_at` using the same `EVIDENCE_SIGNING_KEY` as `exports/ghosting` (single source of truth for signature rails). Full signature never persisted; only 8-char prefix stored for debugging.
- **Scopes (`_SCOPES` in `domains/share/service.py`):**
  - `minimum` → name only.
  - `moderate` → name + education + `us_work_authorized` boolean (US-citizen / US-permanent-resident → true; else false — never surfaces the visa literal).
  - `full` → above + employment_history (title/company/start/end year, NO salary) + top_skills (max 5).
  - **Never surfaced under ANY scope:** sealed claims, ITAR flags, private preferences, salary, visa status literals.
- **TTL:** 1h min → 30d max (`_MIN_TTL_HOURS=1`, `_MAX_TTL_HOURS=720`).
- **Revocation:** checked BEFORE signature (a compromised link stops the moment the owner revokes, even if signature is otherwise valid) → 410 `share_revoked`.
- **Every view receipted** to `share_view_receipts` collection: `{id, share_id, user_id, ip_network, ua_hash, at}`. IP redacted to `/24` (IPv4) or `/48` (IPv6); UA stored as 16-char SHA-256 prefix. Raw IP + raw UA never persisted.
- **PII surface control:** `user.email` explicitly projected out of the users lookup. Constant-time HMAC compare (`hmac.compare_digest`).

**Endpoints:**
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/share/passport` | user + `share_passport` consent | create link |
| GET | `/api/v1/share/passport` | user | list my links |
| DELETE | `/api/v1/share/passport/{share_id}` | user (owner-scoped) | revoke immediately |
| GET | `/api/v1/share/passport/{share_id}/views` | user (owner-scoped) | view-receipt trail |
| GET | `/api/v1/share/p/{share_id}?t={sig}` | **PUBLIC** | filtered read-only Passport |

**Anti-regression locks (14 tests, all green):** `tests/test_phase5a_share_link.py`
- signature stability + scope-differentiation
- IP-redaction to /24
- create → persists row with `revoked_at: null` + signed URL
- create rejects unknown scopes (400)
- revoke marks the row immediately + rejects non-owner (404)
- public GET: filtered payload matches the scope's `_SCOPES` allowlist under `minimum` / `moderate` / `full`
- public GET: 403 on bad signature
- public GET: 410 on expired share
- public GET: 410 `share_revoked` even when signature is valid (revoke > signature priority)
- **PII leak lock:** widest-scope (`full`) payload contains ZERO occurrences of `itar` / `salary` / `sealed` / `preferences` / `visa` — locked case-insensitively.

**Router wired** (`server.py:319` + `server.py`): `app.include_router(share_router)` immediately after `standards_router`.

**Suite delta:** +14 tests · new subtotal (5a only): 14/14 · full-suite pending §closeout.

---

## 5b · MATERIAL A/B TESTING — **LANDED**

**Decide-and-document:**

- No modification to existing `ai_generations` schema. New collection `material_ab_assignments` — one row per `(user_id, application_id, generation_id)` with `variant_label ∈ {"A","B"}` + optional `spectrum_key`.
- Assignment is USER-DRIVEN. We never auto-assign a variant — that would create model-owned bias. All bias in variant selection is user-owned by construction.
- Response attribution: `application_outcomes.event ∈ {interview_scheduled, response_received, offer, rejected_with_reason}`. `ghosted` / `no_response` are NOT counted as responses. This is honest (a rejection IS a response signal).
- **Small-n rail: `_SMALL_N_THRESHOLD = 30`.** Any variant with `n<30` → `small_n: true` + explicit "no significance claim is meaningful" disclaimer. No positive-significance / winner language ever in the notice.
- Endpoints (all `/api/v1/materials/ab`):
  - `POST /attach` — attach or re-attach a label (idempotent on `(user, app, gen)`; re-attach flips the label).
  - `GET /report?spectrum_key=` — per-variant `{n, responded, response_rate, median_days_to_response}`.

**Anti-regression locks (6 tests, all green):** `tests/test_phase5b_materials_ab.py`

Router wired: `app.include_router(materials_ab_router)`.

---

## 5c · EXTENSION CAPTURE-ANYWHERE — **LANDED**

**Decide-and-document (origin sourcing):**

- Founder brief called out two options: cherry-pick the extension dir from `feat/lynk-premium-autopilot` vs. minimal rebuild on main.
- **Chose MINIMAL REBUILD ON MAIN.** Cherry-picking would drag in `dry_run_filler.js` / `hard_stop.js` / autopilot-specific submit selectors — those content scripts violate the founder's explicit 5c constraint "URL capture ONLY — no page-content scraping". Rebuild aligns cleanly with `origin_resolver.py` from Phase 3.

**What shipped in `/app/extension/`:**

- `manifest.json` — MV3 · `permissions: [activeTab, storage]` · `host_permissions: []` (empty ON PURPOSE — cannot inject content scripts, cannot read page DOM, cannot bypass cookies, cannot interact with CAPTCHA).
- `src/lib/constants.js` — `PROHIBITED_HOST_SUFFIXES` = `linkedin.com`, `lnkd.in`, `indeed.com`, `handshake.com`, `joinhandshake.com` — mirrors backend `origin_resolver.py`. `CLIENT_SIDE_HOURLY_CAP = 6`.
- `src/lib/url.js` — same tracking-param strip + host-lowercase canonicalization as backend.
- `src/background/service_worker.js` — 3 client-side rails: https-only, prohibited-host reject, hourly-cap reject. Server rails re-applied.
- `src/popup/popup.html` + `popup.js` — reads active-tab URL only, POSTs to `/api/v1/employers/connect` with `credentials: "include"`.
- `README.md` — explicit "does NOT" list.

**Backend delta: ZERO.** The Phase 3 `POST /api/v1/employers/connect` is the sole entry point; extension is thin. Same origin-resolver + three hard gates + 24h cap + abuse-log path covered by `tests/test_phase3_supply_engine.py` (16 tests) + `tests/test_phase234_tester_leg_fixes.py` (17 tests) applies verbatim.

---

## 5d · INTERVIEW PREP GROUNDED IN PASSPORT — **LANDED**

**Decide-and-document:**

- **LLM integration source:** reuse existing `emergentintegrations.llm.chat.LlmChat` pattern from `services/llm.py`. `EMERGENT_LLM_KEY` already in `.env`. `integration_playbook_expert_v2` was previously called for the original resume-parse integration (same library + key). Model: `openai/gpt-4o`.
- **Grounding rule ("no claim, no sentence") — two-layer firewall:**
  1. **Prompt-layer:** system prompt states 5 hard rules (only reference the JSON claims block; never invent salary/dates/company; strict JSON output; label as "practice").
  2. **Output-layer validator (`_validation_firewall`):** parses the LLM's JSON, extracts tokens from each `sample_answer`, requires ≥1 substantive answer-token to appear in the approved-claim token set. Ungrounded Q&As are DROPPED (never redacted-inline, never delivered).
- **Empty state:** if the user has zero approved claims in the requested category, we return `empty_state: true` + `reason: "no_approved_claims_in_category"` and skip the LLM call (no cost, no fabricated placeholder).
- Consent-scoped: `interview_prep_generate` scope (new in `core/policy.py`).
- Endpoint: `POST /api/v1/interview-prep/generate {category, question_count, focus_hint?}`.
- Every generation logged to `interview_prep_generations` (kept_count, dropped_by_firewall_count auditable).

**Anti-regression locks (7 tests, all green):** `tests/test_phase5d_interview_prep.py`

---

## 5e · RESPONDS-FAST BADGE — **LANDED**

**Decide-and-document:**

- Same source data as `sort=speed` (`services/outcome_autopilot::compute_group_stats`, user-scoped).
- **Thresholds:** `median_days_to_response ≤ 3` AND `responded_count ≥ 3`.
- Employers not meeting BOTH criteria are OMITTED (never labeled "slow").
- Endpoint: `GET /api/v1/badges/responds-fast` → `{responds_fast: {employer_key: {fast, median_days, responded_count, sample_size}}, count, thresholds, notice}`.
- Soft-fail: service exception → empty map (never 500s).

**Anti-regression locks (4 tests, all green):** `tests/test_phase5e_responds_fast.py`

---

## 5f · INTERVIEW OUTCOME RECEIPTS — **LANDED**

**Decide-and-document:**

- Single ledger reused: `application_outcomes`. New events: `interview_scheduled`, `interview_completed`, `interview_ghosted`.
- Each event HMAC-SHA256 signed with the SAME `EVIDENCE_SIGNING_KEY` as `ghosting/export`. Same canonical serializer.
- Phase 4 verify endpoint `POST /api/v1/exports/verify-signature` (`ghosting_verify`) validates 5f receipts natively — one verify path, one key, one canonicalizer. **Locked by cross-domain test `test_signature_verifies_via_existing_exports_verify`.**
- Ghost detection: if the LAST event is `interview_scheduled` and older than `INTERVIEW_GHOST_THRESHOLD_DAYS=14`, surface a `derived_ghosting_signal` but **do not auto-write** the ghost receipt — user must click `POST /confirm-ghost`. No background writes without moment-T consent.
- Endpoints (`/api/v1/interview-receipts`): `POST /record`, `GET /for-application/{id}`, `POST /confirm-ghost`.

**Anti-regression locks (8 tests, all green):** `tests/test_phase5f_interview_receipts.py`

---

## 5g · EMPLOYER DASHBOARD (READ-ONLY v1) — **LANDED**

**Decide-and-document:**

- Requires a **verified** `employer_memberships` row (403 `employer_membership_required` otherwise).
- Cross-employer disclosure is a hard rail. Percentile bucket is computed ONLY over the caller's OWN connected employers (`rank_scope: "own_employers_only"`). Single-employer owner → `rank_scope: "not_available"`.
- Endpoint: `GET /api/v1/employer-dashboard/summary`.
- `application_quality_pass_rate` uses the same `score ≥ 60` threshold as passing-gate checks elsewhere.

**Anti-regression locks (2 tests in `test_phase5ghij.py`, green):** 403 when unverified; own-data-only summary shape; `cross_employer_disclosure: false` on every response.

---

## 5h · LAYOFF-DAY MODE — **LANDED**

**Decide-and-document:**

- One-tap orchestration of EXISTING pieces. **Zero new domain logic.** Endpoint composes preferences + eligibility + jobs + follow-up preset descriptor.
- **No new claims.** **No income promises** — explicit `income_promises: null` + anti-copy scan in test.
- Consent gates on underlying endpoints are intact — endpoint does NOT bypass any of them.
- Endpoint: `GET /api/v1/layoff-day/orchestrate`.

**Anti-regression locks (2 tests in `test_phase5ghij.py`, green):** composes 4 components + income-promise anti-copy scan; honest empty-state when eligibility profile missing.

---

## 5i · PASSPORT-AS-API v1 — **LANDED (spec + build)**

**SPEC (this section IS the spec-before-build called out in the founder brief):**

- Token surface: URL-safe random 43-char string (~256 bits entropy) via `secrets.token_urlsafe(32)`.
- Storage: SHA-256 hash only. Plain token returned exactly ONCE on mint and never persisted or logged.
- Each token binds to ONE user + ONE scope subset (`_SCOPES` reused from 5a Share Link).
- TTL: 1h min → 30 days max.
- Access: `Authorization: Bearer <token>`. Missing → 401. Bad → 401. Revoked → 410. Expired → 410.
- Every access appends `passport_api_receipts` row (`ip_network`, `at`, `scope`, `token_id`); `access_count` incremented on the token row.
- Revocation is immediate — `DELETE /tokens/{id}` sets `revoked_at`; the next `GET /passport` returns 410 without touching passport data.
- Consent-scoped: `passport_api_access` scope (new in `core/policy.py`).

**Endpoints (`/api/v1/passport-api`):** `POST /tokens/mint`, `GET /tokens`, `DELETE /tokens/{id}`, `GET /passport` (Bearer).

**Anti-regression locks (4 tests in `test_phase5ghij.py`, green):** mint returns plain token once + only hash stored; bad scope → 400; access filters by scope + receipt written + counter incremented; revoked → 410 `token_revoked`; missing Bearer → 401.

---

## 5j · COHORT INTELLIGENCE — **LANDED (honest empty state)**

**Decide-and-document:**

- Hard rule same as `/standards`: **HONEST EMPTY STATE. ZERO synthetic cohort numbers.**
- `_MIN_COHORT_SIZE = 50`. Below this: `data_available: false, buckets: [], notice: "needs more users to unlock — no data yet"`. **No synthetic backfill EVER.**
- k-anonymity floor: buckets below `n < 10` are omitted from the surface.
- Coarse grouping only: `eligibility_class`. Never a user-level attribute.
- Endpoint: `GET /api/v1/cohort-intel/summary`.

**Anti-regression locks (2 tests in `test_phase5ghij.py`, green):** pool < 50 → honest refusal; pool ≥ 50 → real aggregates with 5-member bucket omitted (k-anonymity).

---

## SPEC-ONLY items (per founder brief — build nothing)

The founder brief calls out five surfaces that remain SPEC-ONLY on this pass. Documented in `/app/docs/PHASE-5-SPECS/`. They add ZERO runtime surface, ZERO route registration, ZERO tests.

- `PHASE-5-SPECS/VELOCITY-BRIDGE.md`
- `PHASE-5-SPECS/WARM-INTRO-FINDER.md`
- `PHASE-5-SPECS/NEGOTIATION-COPILOT.md`
- `PHASE-5-SPECS/BACKGROUND-PRE-CLEARANCE.md`
- `PHASE-5-SPECS/A2A-PROTOCOL.md`

---

## Suite state at Phase 5 close

```
Phase 0-4 baseline pre-Phase-5:     114 passed / 3 skipped
Phase 5 close (this pass):          164 passed / 3 skipped     (+50 tests, 0 regressions)
```

Per-item test totals:

| Item | Tests | File |
|---|---|---|
| 5a Share Link | 14 | `test_phase5a_share_link.py` |
| 5b Materials A/B | 6 | `test_phase5b_materials_ab.py` |
| 5c Extension | (backend re-uses Phase 3 coverage) | — |
| 5d Interview Prep | 7 | `test_phase5d_interview_prep.py` |
| 5e Responds-Fast | 4 | `test_phase5e_responds_fast.py` |
| 5f Interview Receipts | 8 | `test_phase5f_interview_receipts.py` |
| 5g/h/i/j (batch) | 11 | `test_phase5ghij.py` |
| **Phase 5 subtotal** | **50** | |

**Rails absolute — verified across all 10 items:**
- Consent gates on every new surface (5a `share_passport`, 5d `interview_prep_generate`, 5i `passport_api_access`).
- Caps never bypassed (5c defers to backend 20/24h + client-side 6/hr UX guard).
- Email dry-run (5h `followup_preset.dispatch_mode: "dry_run"`).
- No scraping (5c URL-only; manifest `host_permissions: []`).
- No CAPTCHA interaction (5c cannot inject content scripts).
- Follow-ups never auto-sent (5h explicit + 5f only mints receipts).
- Honest failure/empty states (5b small_n, 5d empty_state, 5e no negative badge, 5j synthetic-refusal, 5h per-component `available: false`, 5g `rank_scope: "not_available"`).
- User-scoped only across every new surface. Cross-user or cross-employer data never crosses the boundary.
- Measured baseline held: 114p/3s → 164p/3s (0 regressions).

**Ready for Phase 5 gate.** Standing by for split tester briefs. Rails held: preview-only, no push (still founder-blocked on GitHub connection), Publish remains founder's.

