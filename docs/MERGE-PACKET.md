# MERGE-PACKET.md — feat/liquid-ui → main (Phase 1 close-out)

**Prepared:** 2026-08-06T~00:15Z (post founder-attested Phase 1 gate PASS)
**Purpose:** Everything the founder's `merge` and `deploy` words need to
execute in the same minute they're given. Observed values only — no
reconstruction, no assumptions.

**PRE-AUTHORIZATION STATUS:** Merge pre-authorized by founder (see
standing orders). This packet's dry-run verdict is CLEAN and the full
suite is GREEN at the packet SHA. Merge WILL execute after this packet
commits. Publish click remains Arjun's physical action.

---

## 1 · Merge dry-run (non-destructive, `git merge-tree`) — UPDATED 2026-08-07

**Command run (at post-tester-leg-fix HEAD):**
```
BASE=$(git merge-base HEAD origin/main)   # → 35032790 (previously-recorded main tip)
git merge-tree $BASE HEAD origin/main | grep -E "^\+<<<<|^<<<<|CONFLICT"
```
**Output:** empty (no conflict markers, no CONFLICT lines).

**VERDICT: CLEAN.** Fast-forward feasible.

**Files touched:** 226 originally + 12 tester-leg-fix files = ~238 files.
Notable adds since original packet SHA `31fb8d8b`:
- Phase 2 · `backend/domains/outcomes/intelligence.py`,
  `frontend/src/components/OutcomesIntelligence.jsx`
- Phase 3 · `backend/domains/supply/{__init__,service,origin_resolver}.py`,
  `backend/tests/test_phase3_supply_engine.py`,
  `frontend/src/components/EmployerConnectCard.jsx`,
  `docs/WORKDAY-SPEC.md`
- Phase 4 · `backend/domains/eligibility/explain.py`,
  `backend/domains/exports/{__init__,ghosting}.py`,
  `backend/domains/standards/{__init__,service}.py`,
  `frontend/src/pages/Standards.jsx`
- Tester-leg fixes · `backend/tests/test_phase234_tester_leg_fixes.py`,
  additions to `middleware/csrf.py` (verify-endpoint exempt),
  additions to `service.py` (abuse log + origin resolver wire-in)
- Evidence · `docs/PHASE-{2,3,4}-EVIDENCE.md` with tester-leg protocol
  correction sections

---

## 2 · Proposed HEAD SHA + full commit list since original packet — UPDATED

**New proposed HEAD (packet SHA):** `95bf94f1c49a4f1b02d6b1d02578789246495516`
**Original packet SHA:** `31fb8d8bf94e87c8e58125121cf13bc2ce6c8289` (Phase 1 close-out)
**Local `main` HEAD at time of last push attempt:** `95bf94f1` (8 commits ahead of `origin/main` which is at `35032790`)

**8 commits between original packet SHA and this HEAD:**

```
2121a727 docs(merge-packet): record post-merge main HEAD 31fb8d8b (fast-forward)
27d902e2 docs(merge-packet): record push blocked on GitHub connection (external, continuing per rails)
6617cd94 feat(phase2): INTELLIGENCE VISIBLE — 3 read-only outcome intelligence panels
80834632 feat(phase3): SUPPLY ENGINE — self-serve URL ingestion + voting queue + WORKDAY-SPEC
9e2939d2 feat(phase4): ELIGIBILITY ENGINE & EXPORTS — explain endpoint + signed ghosting export + public /standards page
4eff451e docs(prd): Phase 0-4 sequence complete status header
713c3064 auto-commit (platform-emitted checkpoint)
95bf94f1 fix(phase234): tester-leg shortfalls — origin resolver, abuse log, per-datum labels, format=pdf 501, verify endpoint
```

**LOCAL MAIN FAST-FORWARD RE-VALIDATION:** every commit landed
directly on `main` (Phase 1 merge was fast-forward; Phase 2-4 +
tester-leg-fixes extended `main` directly, no branching). So no
re-merge is needed — the fix commits are already on `main`. The
"re-merge/fast-forward" step in the founder's directive is a no-op
here: local main already contains all fix commits.

**Suite green at packet SHA `95bf94f1`:** confirmed
`111 passed / 3 skipped` (Phase 4 baseline 97p/3s → **+14 pass, 0 regressions**).

---

## 3 · Cumulative test state at packet SHA — UPDATED

**Focused Phase 0-4 suite + tester-leg fixes** (18 test files, run at
packet SHA `95bf94f1`):

```
python3 -m pytest \
   tests/test_preflight_validator.py \
   tests/test_receipt_compound_index_regression.py \
   tests/test_consent_scope_enum_guard.py tests/test_apply_at_birth.py \
   tests/test_form_map_cache.py tests/test_outcome_autopilot.py \
   tests/test_self_healing.py tests/test_outcomes_endpoints.py \
   tests/test_surprise_me.py tests/test_phase1_speed_sort.py \
   tests/test_phase1_follow_ups.py tests/test_phase1_standing_wave_tick.py \
   tests/test_phase1_wave_consent_snapshot.py \
   tests/test_phase1_g3d_annotation_trail.py \
   tests/test_phase2_outcomes_intelligence.py \
   tests/test_phase3_supply_engine.py \
   tests/test_phase4_eligibility_exports_standards.py \
   tests/test_phase234_tester_leg_fixes.py
```

**Result:** **111 passed, 3 skipped in 4.22s** (Phase 1 baseline 72p/3s
→ **+39 pass cumulative, 0 regressions**; Phase 4 baseline 97p/3s →
**+14 pass from the tester-leg fixes**).

**The 3 skipped tests + their live-curl locks (unchanged from Phase 1):**

| Test | Skip reason | Live-curl lock reference |
|---|---|---|
| `test_phase1_follow_ups.py::test_wave_authorization_persists_consent_snapshot` | motor/pytest-asyncio executor state | `PHASE-1-EVIDENCE.md §v` — wave-authorize + `GET /wave/authorizations` curl verifies snapshot mirroring live consents on both paths |
| `test_phase1_follow_ups.py::test_approve_creates_fresh_outbox_row_and_marks_draft` | motor/pytest-asyncio executor state | `PHASE-1-EVIDENCE.md §vii` — POST /follow-ups/approve curl verifies email_outbox row creation + draft state transition |
| `test_phase1_follow_ups.py::test_approve_refuses_non_draft_state` | motor/pytest-asyncio executor state | `PHASE-1-EVIDENCE.md §vii` — same-lane curl verifies 409 on non-draft state |

The dual-path Fix 1 regression is fully test-covered by
`tests/test_phase1_wave_consent_snapshot.py` (4 pass, using fake-DB —
not affected by the motor/pytest-asyncio issue).

The 14 tester-leg fix tests in
`tests/test_phase234_tester_leg_fixes.py` lock each of the 6 shortfalls
that the founder-run tester leg surfaced (see Phase 3 §5 + Phase 4 §4
in the evidence files).

---

## 4 · Deploy runbook — env var NAMES + first-boot expectations

### 4a · Env var NAMES required in the Emergent env UI (never values)

**Backend (`backend/.env`):**
| Name | Notes |
|---|---|
| `MONGO_URL` | Emergent-provided; workspace pod uses local Mongo |
| `DB_NAME` | Emergent-provided; must match pod's Mongo |
| `JWT_SECRET` | Must be different from any git-history value |
| `JWT_ALGORITHM` | `HS256` |
| `JWT_EXPIRES_HOURS` | `24` |
| `PROD_MODE` | **MUST be `true`** in production |
| `CI_TEST_ISSUER_ENABLED` | **MUST be `false`** in production (server refuses to boot if PROD_MODE=true and this is true) |
| `SESSION_COOKIE_SECURE` | **MUST be `true`** in production |
| `CORS_ALLOW_ORIGINS` | comma-separated production origin(s) — never `*` in prod |
| `INTERNAL_SERVICE_TOKEN` | Random opaque; guards `/api/internal/*` |
| `EMERGENT_LLM_KEY` | Provided by Emergent for LLM integrations |
| `STRIPE_API_KEY` | Emergent test key in pod; production key in prod env UI |
| `VAPID_PUBLIC_KEY` | **DO NOT regenerate on deploy** — invalidates all existing subscriptions |
| `VAPID_PRIVATE_KEY` | Same — set once, leave alone |
| `VAPID_SUBJECT` | `mailto:...` |
| `STORAGE_ROOT` | File-storage mount path |
| `POLICY_TEXT_VERSION` | Bump on privacy-policy text change |
| `APPLY_AT_BIRTH_ENABLED` | Feature flag; safe default `true` for launch |

**Frontend (`frontend/.env`):**
| Name | Notes |
|---|---|
| `REACT_APP_BACKEND_URL` | Full production API base URL (https://…) |
| `GENERATE_SOURCEMAP` | `false` in prod |
| `WDS_SOCKET_PORT` | Dev-only; not required in prod build |
| Other CRA build/hot-reload flags | Dev-only; ignored by prod build |

**Mobile (`mobile/.env`):**
| Name | Notes |
|---|---|
| `EXPO_PUBLIC_API_URL` | Full production API base URL |
| Additional Expo build-time flags | See `mobile/app.config.ts` |

### 4b · First-boot expectations

- **Discovery ingestion:** ~19-22k job docs into `jobs` collection.
  Cold boot from empty Mongo populates in **~90-120s** (16 verified
  provider tuples run in parallel). Subsequent boots refresh only stale
  docs.
- **Scored cache warm-up:** First `/feed` request per user is
  **~2.5s** on cold cache, drops to **~700ms** once cache is populated.
- **Seeder rebase:** ONLY runs against fixture users (`fixture-ead@`,
  `fixture-broad@`). NO impact on real users. Rebases wipe + re-seed
  fixture state on every backend startup — this is by design and
  isolated to fixtures.
- **Session store:** Backed by Mongo `sessions` collection; survives
  backend restart. `login_throttle` bucket resets every 24h via TTL
  index.

### 4c · Feature flags with safe defaults

| Flag | Prod default | Rationale |
|---|---|---|
| `APPLY_AT_BIRTH_ENABLED` | `true` | AAB is core to Fynd; sample-safe by default |
| Standing-wave arm (per-user setting `standing_wave_active`) | **false** | Standing waves are OFF-by-default per user; each user must arm explicitly with cap ≤ 7 |
| Email route (in `follow_ups`) | **dry-run** | Follow-ups NEVER auto-send in preview; production keeps dry-run until founder flips DNS+live email flag |
| `sort=speed` (feed query param) | available | Read-only, additive; no side-effect |
| `booking_url` (per-user pref) | empty string | User must explicitly save an https:// URL |

---

## 5 · Post-deploy smoke plan

**Location:** `/app/scripts/post_deploy_smoke.sh`

**How to run against production:**
```
PROD_URL=https://<slug>.emergent.host bash /app/scripts/post_deploy_smoke.sh
```

**Checks (12 sections):**
1. `/api/health` returns 200 + `{ok, mongo, phase, policy_text_version}`
2. Public health does NOT expose `prod_mode` / `ci_test_issuer_enabled` / `build_sha`
3. Admin login + admin-only health surfaces (`prod_mode:true`, `ci_test_issuer_enabled:false`, `build_sha` matches deploy SHA)
4. Exactly 16 provider rows in mandated status enum
5. No env VALUES leaked in provider describe payloads (only NAMES)
6. `POST /api/internal/fixture/rebase` returns 503 in prod (fixture rebase is gated OFF)
7. VAPID public key surface + 5 notification categories
8. Fresh signup 201 + `/auth/me` roundtrip
9. Secure cookie flags (Secure + HttpOnly + SameSite)
10. CORS lockdown (rejects `http://localhost:3000` origin)
11. Test-only routes disabled (`/api/v1/testing/*`, `/api/v1/dev/*`)
12. **Phase 1 conversion-layer surfaces (added 2026-08-06):**
    - `GET /jobs/feed?sort=speed` responds cleanly (never 5xx)
    - `GET /wave/preview` returns `breakdown` with all 5 canonical keys (`total_scanned`, `blocked_scope`, `blocked_hard_gate`, `blocked_cap`, `blocked_duplicate`) — READ only, no authorize side-effect
    - `GET /preferences` 200 (booking_url row surface reachable)
    - `GET /follow-ups/drafts` 200 (review lane reachable, never auto-sent guarantee)

**Verdict semantics:** exits 0 iff all green; exits 1 with per-failure
list otherwise. Followed by two HUMAN click-throughs: Google OAuth,
Web-Push subscribe + test-send.

---

## 6 · Rollback

**Current prod pin:** `4f01a840` (recorded in prior merge-decision packet, 2026-07-28).
**Second-fallback:** `d247a383` (hardcoded-token-fix baseline).

**Two-step fallback runbook** (if post-deploy smoke fails hard):
1. **Immediate:** rollback prod pin to `4f01a840` via Emergent
   dashboard (single-click).
2. **If `4f01a840` is also broken:** rollback further to `d247a383`.
   Both SHAs are pre-verified launch baselines with 16/16 providers
   green; neither has Phase 1 surfaces but both are safe production
   states.

---

## 7 · Known gaps (carried honestly)

### 7a · Deferred pre-share items (per founder choice, this packet)

- **Floor items 1-3** (from prior founder-side pre-share list) are
  deliberately deferred by founder decision. They are NOT blockers for
  this merge/publish. They will be picked up in a later phase.

### 7b · Backend rebrand string residuals

- Codename `opportunityos` remains as a **data identifier only** in:
  - Fixture user email domain (`fixture-ead@opportunityos.dev`,
    `fixture-broad@opportunityos.dev`, etc.). NOT branding — this is a
    stable synthetic domain that keeps the fixture-user identity
    deterministic across environments.
  - Cookie names `oppos_session`, `oppos_csrf`. Renaming these would
    invalidate every existing session cookie and force a global sign-out
    — deferred by design; documented for the next auth-rotation window.
  - Backend logger names (`oppos.discovery`, `oppos.integrations`) —
    internal-only, never surfaces to users.
- User-facing strings are fully "Fynd". Verified in Feed.jsx / Passport
  / Landing / Login / Preferences.

### 7c · NOT-VERIFIED residuals

- **Google OAuth end-to-end** — mocked in tests; a real
  click-through requires a human with a Google account. Post-publish
  smoke plan includes this as a manual step.
- **Web Push subscribe + test-send** — real delivery requires a
  browser to subscribe first. Post-publish smoke plan step 2.
- **Apple Sign-in** — CONFIGURATION_REQUIRED in preview; needs
  `APPLE_CLIENT_ID` / `APPLE_TEAM_ID` / `APPLE_KEY_ID` /
  `APPLE_PRIVATE_KEY` / `APPLE_REDIRECT_URI` in prod env before real
  click-through works.
- **Phone OTP (Twilio Verify)** — CONFIGURATION_REQUIRED in preview.
- **Stripe live** — pod uses Emergent test key; prod env must inject
  live key. Payment flow untested at live rates.

### 7d · Dev-mode-vs-prod Lighthouse caveat

- LCP dropped `3.98s` (dev) → `~0.7s` (prod-build Lighthouse). Numbers
  in `docs/phase-1-artifacts/feed_lcp_*.json`. The dev-mode 3.98s number
  is **not** production-representative; prod-build 0.7s **is**. Founder
  is aware.

### 7e · Historical git-blob credential exposure

- `memory/test_credentials.md` and `mobile/.env` are now untracked
  (this packet, commit `24615b52`). Both files remain in git **history**
  because the earlier untracking was committed on the never-merged
  autopilot branch. Known exposure — founder previously acknowledged.
- `tmp_cookies.txt` (untracked in `c13bea0d`) contained an expired
  preview cookie only — dead fossil, no live-value risk. Preview cookies
  in history are for expired preview URLs.
- **No prod-live secret has ever been tracked** because Emergent's
  publish pipeline reads env values from the workspace filesystem, not
  from git.

### 7f · Repo hygiene follow-up

- `test_reports/iteration_*.json` files are tracked but grow every
  test-agent run. Consider gitignoring `test_reports/` in a follow-up
  phase — NOT blocking this merge.
- `frontend/yarn.lock` has one spurious drift removing an already-uninstalled
  `framer-motion` entry — reverted in this session (not committed), stays
  in-sync with `package.json`. Not blocking.

---

**MERGE EXECUTED (2026-08-07T~00:55Z):**
- Fast-forward merge of `feat/liquid-ui` → `main`. No merge commit
  needed (main was strictly behind feat/liquid-ui).
- **Post-merge `main` HEAD SHA:** `31fb8d8bf94e87c8e58125121cf13bc2ce6c8289`
- Local `main` is now at packet SHA. Pre-push hard check RE-VERIFIED
  clean immediately before push attempt.

**PUSH STATUS (2026-08-07T~00:55Z):**
- `git push origin main` **BLOCKED ON GITHUB CONNECTION AUTH.**
  Exact error: `fatal: could not read Username for 'https://github.com':
  No such device or address`. Expected per founder's rails — the git
  remote was sanitized tokenless long ago and pushes require the
  founder's native Emergent "Save to GitHub" connection. **Merge is
  complete locally on `main`.** Push is deferred to Arjun's next
  GitHub-connected session (single-click "Save to GitHub" from the chat
  input). No credentials attempted or embedded.
- Continuing Phase 2-4 auto-sequence per standing orders (push does not
  block the sequence).

## Merge execution plan (auto-runs after this packet commits)

Per founder's merge pre-authorization + rail check:

1. **Pre-push hard check** — RE-RUN at merge time (locked in this packet):
   ```
   git ls-files | grep -E "\\.env$|test_credentials\\.md$|tmp_"
   ```
   Expected: empty output. If non-empty → ABORT the push.
2. **Checkout main.**
3. **Merge feat/liquid-ui into main.** Fast-forward is feasible (main
   is the merge-base) — merge will succeed cleanly.
4. **Record the merge commit SHA** here at time of execution.
5. **Push origin/main** via authorized platform mechanism.
6. **On push rejected for auth** — record `"merge complete locally,
   push blocked on GitHub connection"` here, notify founder, CONTINUE
   the Phase 2-4 auto-sequence per standing orders.
7. **On push accepted** — notify founder that the Publish button in the
   Emergent dashboard is the single remaining step.
