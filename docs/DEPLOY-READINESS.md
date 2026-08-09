# DEPLOY-READINESS.md — read-only health check

**Prepared:** 2026-08-09 (read-only diagnostics, no code changes, no service restarts).
**Local `main` HEAD at check time:** `db142a0b` (platform auto-commit, parent `72e093be` docs-closeout; substantive closeout SHA = `b87d9c14`).
**Overall verdict:** **NOT-READY** — one hard blocker (§9a: `mobile/.env` missing on disk, matches observed deploy-pipeline failure) + one non-blocking docs drift (§9b: MERGE-PACKET.md §2 stale).

---

## 1 · SERVICES

- supervisor: **backend RUNNING pid 90 uptime 0:21:56 · frontend RUNNING pid 92 uptime 0:21:56 · mongodb RUNNING pid 96 uptime 0:21:56 · mobile RUNNING pid 95 · nginx-code-proxy pid 89 · code-server STOPPED (Not started — inactive by design)**
- `GET /api/health` → **HTTP 200 in 311ms · body `{"ok":true,"mongo":true,"phase":6,"policy_text_version":"1.0"}`**
- `GET /api/openapi.json` → **HTTP 200 · `openapi=3.1.0` · paths=176 · total FastAPI routes=192 (non-openapi routes for health/internal)**

## 2 · DATA

- `jobs.count_documents({})` = **26,352** · `jobs.count_documents({"status":"live"})` = **22,564** (~85.6% live)
- Last discovery run (from `oppos.discovery` log, 2026-08-07T01:48:22Z): **`elapsed_s=130.41 · companies_kept=157 · companies_dropped=1 · postings_seen=22472 · postings_inserted=1 · postings_updated=22471 · greenhouse=95 · lever=6 · ashby=56`**
- Last lifecycle sweep (`lifecycle_sweep` sub-payload of same run): **`boards_swept=157 · boards_skipped_ambiguous=1 · boards_errored=0 · closed_total=1 · stamped_total=22472 · error=None`**
- AAB scheduler state: `apply_at_birth.scheduler: activated (tick_interval_s=300, hot=1200s warm=7200s cold=21600s)`; last tick at 2026-08-07T01:46:43Z: **`due=60 polled=60 errored=0 closed=2 tiers={hot:15,warm:45,cold:0} median_lag_min=14.4`**. `APPLY_AT_BIRTH_ENABLED` env var: **unset in current pod** (safe default `false`; production runbook mandates `true` — see §6).
- Discovery/lifecycle/AAB do NOT persist to `discovery_runs` / `lifecycle_sweeps` / `aab_ticks` collections; observability is via `oppos.discovery.scheduler` structured log lines (verified by tailing `/var/log/supervisor/backend.err.log`).

## 3 · BUILD

- Frontend production build (`yarn build` in `/app/frontend`): **exit 0 in 6.55s**. Bundle emitted to `frontend/build/`; largest chunks ≤ few dozen KB; homepage `/`. No compile warnings surfaced at the tail.
- Backend module import: `python3 -c "import server; print(len(server.app.routes))"` → **192 routes registered, no import errors**.

## 4 · TESTS

- Focused Phase 0-4 suite + tester-leg fixes + 2026-08-08 closeout (18 test files, run at HEAD `db142a0b`): **`114 passed, 3 skipped in 3.60s`** — MATCHES the recorded 114p/3s baseline from MERGE-PACKET.md §3 (0 regressions).
- The 3 skipped tests are **motor/pytest-asyncio incompatibility skips**, locked by live-curl evidence in `PHASE-1-EVIDENCE.md §v` and `§vii`. They are not functional gaps.

## 5 · GIT

- Branch: **main** · HEAD SHA: **`db142a0b`** (platform auto-commit; parent `72e093be` docs-closeout; substantive closeout `b87d9c14`)
- Working tree: **CLEAN** (`git status --short` = empty)
- Pre-push secret check re-run: `git ls-files | grep -E "\.env$|test_credentials\.md$|tmp_"` → **empty · CLEAN · safe to push**
- MERGE-PACKET.md FINAL SHA claim: `b87d9c14` (§1, §3, §8). **DRIFT FOUND** — §2 still names `95bf94f1` as "New proposed HEAD" (stale from prior packet iteration). Non-blocking but flagged in §9b.
- Commits ahead of `origin/main` (`35032790`): **129** (all Phase 0-4 work + tester-leg + closeout + auto-commits).

## 6 · CONFIG READINESS

### 6a · Env var NAMES required for production (values NEVER shown)

Backend: **`MONGO_URL · DB_NAME · JWT_SECRET · JWT_ALGORITHM · JWT_EXPIRES_HOURS · POLICY_TEXT_VERSION · STORAGE_ROOT · EMERGENT_LLM_KEY · INTERNAL_SERVICE_TOKEN · CI_TEST_ISSUER_ENABLED · PROD_MODE · CORS_ALLOW_ORIGINS · SESSION_COOKIE_SECURE · STRIPE_API_KEY · VAPID_PUBLIC_KEY · VAPID_PRIVATE_KEY · VAPID_SUBJECT · APPLY_AT_BIRTH_ENABLED`**

Frontend: **`REACT_APP_BACKEND_URL · GENERATE_SOURCEMAP`** (dev-only extras: `WDS_SOCKET_PORT · WATCHPACK_POLLING · CHOKIDAR_USEPOLLING · BROWSER · DANGEROUSLY_DISABLE_HOST_CHECK · ESLINT_NO_DEV_ERRORS · TSC_COMPILE_ON_ERROR`).

Mobile: **`EXPO_PUBLIC_API_URL`** (per MERGE-PACKET §4a). **`mobile/.env` is missing on disk today — see §9a.**

### 6b · Feature flags + safe defaults

| Flag | Prod default | Read where |
|---|---|---|
| `APPLY_AT_BIRTH_ENABLED` | **true** (per MERGE-PACKET §4c; code default is `false` — so prod env MUST set it) | `backend/services/apply_at_birth.py:29` |
| `WEEKLY_DIGEST_EMAIL_ENABLED` | **off** (code default: any value ≠ `"true"` is OFF) | `backend/domains/outcomes/intelligence.py:284` |
| `WORKDAY_DISCOVERY_ENABLED` | **off** (spec-only in this phase; enabling requires spec sign-off) | `backend/domains/standards/service.py:74` |
| `WORKDAY_LIVE_ENABLED` | **off** (production ingestion off in this phase) | `backend/domains/standards/service.py:75` |
| `CI_TEST_ISSUER_ENABLED` | **false** (server refuses to boot if `PROD_MODE=true` and this is `true`) | server preflight |
| Standing-wave per-user arm (`standing_wave_active`) | **false** (per-user opt-in; consent-gated on every fire) | `Phase 1` rails |
| Email route (`follow_ups`) | **dry-run** (never auto-sent in preview; production keeps dry-run until DNS+live email flip) | `Phase 1` rails |
| `sort=speed` (feed query param) | available (read-only, additive, no side-effect) | feed handler |
| `booking_url` per-user | empty string (user must save an https:// URL) | Preferences |

- **PRIVATE_AUTOPILOT:** no env-flag references found in backend source; the private-autopilot lane is off/absent on this branch (`feat/lynk-premium-autopilot` is a separate branch, not merged into main).
- **STANDING_WAVE:** no top-level env flag; standing-wave is per-user-arm, consent-gated on every tick.

### 6c · Boot-secret dependencies

- No code path requires an unset secret to boot. `EMERGENT_LLM_KEY`, `VAPID_*`, `STRIPE_API_KEY` are present in the current pod's `backend/.env`.
- `USAJOBS_API_KEY` / `USAJOBS_USER_AGENT_EMAIL` are ABSENT and produce a documented `status: "config_required:missing=..."` in the discovery report (soft-fail: 0 postings from USAJobs; other providers ingest normally). Non-blocking for launch.
- `APPLE_*` and Twilio OTP env vars are ABSENT — documented as click-through-CONFIGURATION_REQUIRED (§9d), non-blocking for launch.

## 7 · FIRST-BOOT EXPECTATIONS (observed figures only)

- Cold discovery ingest: **130.41s** (observed 2026-08-07T01:48:22Z) for **157 companies · 22,472 postings · 3 sources (greenhouse/lever/ashby)**. Matches MERGE-PACKET §4b estimate of "~90-120s" within variance (single-run @130s at pod cold-start).
- Time-to-first-jobs at boot: **≤ 3s per scheduler kick cadence** (discovery task created within ~11-12s of process start; `refresh_all` kicked ~10s later).
- Live jobs stabilized in cache: `jobs.status=live=22,564` at check time.
- Index creation idempotency: backend re-import via `python3 -c "import server"` returned **192 routes with no error**, implying startup-time index creation is idempotent (no duplicate-key or IndexOptionsConflict errors surfaced in tail 300 of backend.err.log).

## 8 · SMOKE PLAN

- `/app/scripts/post_deploy_smoke.sh`: **EXECUTABLE** (`-rwxr-xr-x 15,671 bytes`).
- Endpoint list touched by the smoke script (grep-verified against current 176-path OpenAPI surface):
  - `/api/health` ✓
  - `/api/v1/auth/login`, `/api/v1/auth/signup`, `/api/v1/auth/me`, `/api/v1/auth/apple/status` ✓
  - `/api/v1/admin/health`, `/api/v1/admin/integrations` ✓
  - `/api/v1/consents`, `/api/v1/passport/activation-status` ✓
  - `/api/v1/notifications/vapid-public-key` ✓
  - `/api/v1/jobs/feed` (and `?sort=speed`) ✓
  - `/api/v1/wave/preview` ✓
  - `/api/v1/privacy/export`, `/api/v1/privacy/export/<job_id>` ✓
  - `/api/internal/fixture/rebase` (asserts 503 in prod) ✓
  - `/api/v1/testing/*` and `/api/v1/dev/*` (asserts test-only routes disabled in prod) ✓
- **No stale endpoint references found.** All URLs in the smoke script exist in the current API surface.

## 9 · KNOWN GAPS

### 9a · **HARD BLOCKER · `mobile/.env` missing on disk**

- **Observed:** `ls -la /app/mobile/.env` → `No such file or directory`.
- **Root cause:** `.gitignore:12` correctly excludes `mobile/.env` from git tracking; however the file does not exist on the workspace filesystem either, so the Emergent deploy pipeline's build-context read fails on `open .../app/mobile/.env: no such file or directory`.
- **Effect on prod:** deploy build cannot complete until the file exists on disk (populated with at least `EXPO_PUBLIC_API_URL=<prod backend url>` per MERGE-PACKET §4a).
- **Handoff-summary claim:** "mobile/.env untracked but kept on disk". **Current state contradicts that claim** — the file is not present on disk in this pod at check time.
- **Remediation (owner: founder, external — no code change from agent):** create `mobile/.env` on disk with `EXPO_PUBLIC_API_URL` (and any other required Expo build-time vars per `mobile/app.config.ts`) before re-triggering deploy. Keep it git-ignored (already is).

### 9b · Non-blocking · MERGE-PACKET.md §2 stale SHA reference

- **Observed:** MERGE-PACKET.md §2 header still names `**New proposed HEAD (packet SHA):** 95bf94f1c49a...` (prior packet iteration). §1, §3, and §8 correctly show the current FINAL SHA `b87d9c14`. My prior refresh of §2 no-op'd silently (docs bug in the search-replace pipeline this session).
- **Effect:** documentation-only drift; no runtime impact; no deploy impact. Historian could be confused by the internal inconsistency.
- **Remediation (owner: agent, deferred per this read-only directive):** re-run §2 refresh in a follow-up doc-only commit when read-only mode ends.

### 9c · Push blocked on GitHub connection auth (external — expected)

- `git push origin main` blocked with `fatal: could not read Username for 'https://github.com': No such device or address` (documented in MERGE-PACKET §PUSH STATUS and §7c). The git remote is intentionally tokenless. Push clears when founder uses the native "Save to GitHub" flow from a GitHub-connected session.

### 9d · Click-through-required items (unchanged from MERGE-PACKET §7c)

- **Google OAuth end-to-end** — real click-through requires a human with a Google account. Covered in the smoke plan as a manual step.
- **Web Push subscribe + test-send** — real delivery requires a browser to subscribe first.
- **Apple Sign-in** — CONFIGURATION_REQUIRED in preview; prod env must inject `APPLE_CLIENT_ID` / `APPLE_TEAM_ID` / `APPLE_KEY_ID` / `APPLE_PRIVATE_KEY` / `APPLE_REDIRECT_URI`.
- **Phone OTP (Twilio Verify)** — CONFIGURATION_REQUIRED in preview.
- **Stripe live** — pod uses Emergent test key; prod env must inject live key.
- **USAJobs** — `status: "config_required:missing=USAJOBS_API_KEY,USAJOBS_USER_AGENT_EMAIL"` in every discovery run. Soft-fail: other providers ingest normally.

### 9e · Historical git-blob credential exposure (unchanged from MERGE-PACKET §7e)

- `memory/test_credentials.md` and `mobile/.env` are untracked in the current tree (commit `24615b52`) but remain in git **history** from before the untracking commit landed. Known exposure — founder previously acknowledged. `tmp_cookies.txt` (untracked in `c13bea0d`) contained an expired preview cookie only. No prod-live secret has ever been tracked.

### 9f · Deferred pre-share items (unchanged from MERGE-PACKET §7a)

- Floor items 1-3 (prior founder-side pre-share list) are deliberately deferred by founder decision. Not blockers for this merge/publish.

---

## Verdict summary

| # | Item | Status |
|---|---|---|
| 1 | Services | ✓ GREEN |
| 2 | Data | ✓ GREEN |
| 3 | Build | ✓ GREEN |
| 4 | Tests | ✓ GREEN (114p/3s matches baseline) |
| 5 | Git | ✓ GREEN (tree clean, pre-push clean) |
| 6 | Config readiness | ✓ GREEN (no unset secrets required to boot) |
| 7 | First-boot expectations | ✓ GREEN (measured 130s/157 companies/22.5k postings) |
| 8 | Smoke plan | ✓ GREEN (executable, no stale endpoints) |
| 9a | mobile/.env missing on disk | **✗ BLOCKING (deploy pipeline dependency)** |
| 9b | MERGE-PACKET.md §2 SHA drift | ⚠ NON-BLOCKING (docs-only) |
| 9c-9f | Push / click-throughs / history / deferred | ⚠ KNOWN, DOCUMENTED, NON-BLOCKING |

**Overall: NOT-READY** — resolve §9a (create `mobile/.env` on disk with `EXPO_PUBLIC_API_URL` at minimum) then retry deploy. Every other check is green at HEAD `db142a0b` / closeout SHA `b87d9c14`.
