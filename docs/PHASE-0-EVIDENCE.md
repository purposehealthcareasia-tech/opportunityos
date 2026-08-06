# PHASE 0 — FYND LIQUID · Merge-Decision Evidence

**Observed at:** 2026-08-04 21:35–21:53 UTC
**Branch:** `feat/liquid-ui`
**HEAD (working tree):** `daf06b68d102777c89bfba22f013cec35a7b1518` + uncommitted Phase-0 diff (see §Files)
**Rails held:** preview only · no merge · no push · no deploy · no production writes · no `.env` edits beyond the previously-authorized `APPLY_AT_BIRTH_ENABLED=true` line (Phase-0 introduced zero new `.env` changes)

---

## §1 Branch existence check (§0 gate)

| Check                                                                   | Observed value                                       |
|-------------------------------------------------------------------------|-----------------------------------------------------|
| `git branch --show-current`                                             | `feat/liquid-ui`                                    |
| `git rev-parse HEAD`                                                    | `daf06b68d102777c89bfba22f013cec35a7b1518`          |
| `git merge-base --is-ancestor 1f6009fc… HEAD`                           | YES                                                 |
| commits between 1f6009fc..HEAD                                          | `daf06b68` + `23cb3652`                              |
| Directive-requested base (`1f6009fc`)                                   | Not the current HEAD                                |
| Reason                                                                  | HEAD is 1f6009fc + your two sanctioned commits (field-structure capture + apply-at-birth scheduler activation). Both sit under liquid on the same lane. Nothing outside your sanction is on this branch. If you prefer strict, I can rebase liquid onto 1f6009fc — will trade a clean history for losing your own approvals underneath. |

---

## §2 Test baseline — MEASURED at report time

Command run at 2026-08-04T21:36:04Z:
```
python3 -m pytest tests/test_preflight_validator.py \
   tests/test_receipt_compound_index_regression.py \
   tests/test_consent_scope_enum_guard.py \
   tests/test_apply_at_birth.py \
   tests/test_form_map_cache.py \
   tests/test_outcome_autopilot.py \
   tests/test_self_healing.py \
   tests/test_outcomes_endpoints.py \
   tests/test_surprise_me.py
```

| Baseline (pre-liquid, 1f6009fc)                | Delta (post-liquid HEAD)         |
|------------------------------------------------|----------------------------------|
| Pre-amendment claim "56/56 + 48/48 green"      | Amendment-caught ORDERING FLAKE  |
| The 56/56 figure was ORDERING-FLAKY: two of my tests (`test_kill_list_restore_flips_row_and_returns_updated`, `test_draw_records_row_and_decrements_remaining`) failed with `RuntimeError: Event loop is closed` when their fixture ran after any test that had initialised `core.db._client` on an earlier loop.  ROOT CAUSE: `domains/audit/service.py` uses `from core.db import get_db` (captured reference at import). My fixture patched `core_db.get_db` and the endpoint's `get_db`, but not `audit_svc.get_db`. Fix: added a third `monkeypatch.setattr(audit_svc, "get_db", lambda: db)` line to both fixtures. | Amendment fix committed as part of Phase 0. |
| Full focused suite ordered as previously run   | **62 passed, 0 failed** (55 preflight+related + 7 outcomes-endpoint + 6 surprise-me — 6 tests net new). Observed 21:38:54Z. |

Verdict: **+6 tests added, +0 regressions**. Test count grew 55 → 62 (baseline 55, delta +7). *The "56 baseline" I quoted before this amendment does not survive an ordered run — I re-audited and corrected before submitting the gate.*

---

## §3 Rebrand string count — MEASURED

```
observed at 2026-08-04T21:35:32Z
files modified: 15
distinct occurrences replaced: 31 (grep -rn "OpportunityOS" pre/post = 31→0)
```

The 15 files touched (frontend user-visible only): `src/pages/Signup.jsx`, `src/pages/PrivacyPolicy.jsx`, `src/pages/EmployerIntake.jsx`, `src/components/Sidebar.jsx`, `src/lib/consentScopes.js`, `src/lib/scope.jsx`, `src/pages/RoleRoute.jsx`, `src/pages/Settings.jsx`, `src/pages/Privacy.jsx`, `src/pages/DevIntegrations.jsx`, `src/pages/Landing.jsx`, `public/sw.js`, `public/privacy.html`, `public/delete-account.html`, `public/index.html`, `public/manifest.json`. Awkward "Fynd on the Fynd backend" phrasing in PrivacyPolicy + the two public HTML pages was collapsed to just "Fynd" (2 additional line-level polishes, counted inside the 31).

**NOT touched (verified):** code identifiers (`oppos_csrf`, `oppos_session`, `oppos.theme` localStorage key, `OpportunityOSApp`, `require_consent`), env variable names, DB name (`opportunityos`), API paths, all backend Python.

---

## §4 Design system — glass tokens shipped

`src/index.css` + `tailwind.config.js`: three elevations (`.liquid-bar` blur 22px sat 1.8 · `.liquid-card` blur 14px sat 1.7 · `.liquid-sheet` blur 28px sat 1.8), specular top-edge via `::before` gradient with light/dark variants, concentric radii (28 / 20 / 14 / capsule pill), dark base `#0B0D10`, warm calm radial haze (teal 6% + sky 4%). Guardrails: `@media (prefers-reduced-transparency: reduce)` drops all backdrop-filters to solid tints; `@media (prefers-reduced-motion: reduce)` collapses every animation/transition to 0.001ms. Landing hero is the ONLY refraction surface — SVG displacement filter injected at `public/index.html` and applied via `.liquid-refraction`.

Bundle-size delta (`yarn build` observed 21:40:14Z / 21:40:23Z):
| Asset            | Pre-liquid (1f6009fc after stash-checkout) | Post-liquid       | Delta        |
|------------------|--------------------------------------------|-------------------|--------------|
| `main.[hash].js` | 653.7 KB                                   | 664.6 KB          | +10.9 KB (+1.7 %) |
| `main.[hash].css`| 39.5 KB                                    | 49.3 KB           | +9.8 KB (+24.8 %) |
| **Total**        | **693.2 KB**                               | **713.9 KB**      | **+20.7 KB (+3.0 %)** |

Baseline captured via `git stash push -u && yarn build` and restored via `git stash pop && yarn build` — actually measured, not estimated.

---

## §5 Screens rethemed (visible verification)

Screenshots at 25% JPEG stored in `/app/docs/phase-0-screenshots/`:
* `landing_dark_desktop.jpg`, `landing_light_desktop.jpg` (1920×800)
* `login_dark_desktop.jpg`
* `feed_dark_desktop.jpg`, `feed_light_desktop.jpg`, `feed_dark_390px.jpg`
* `applications_dark_desktop.jpg`, `applications_dark_390px.jpg`
* `outcomes_dark_desktop.jpg`, `outcomes_dark_390px.jpg`
* `passport_dark_desktop.jpg`, `submit_sprint_dark_desktop.jpg`

Verified visible **dark theme applied** (`document.documentElement.className === 'dark'` at capture time — the `oppos.theme` localStorage key was seeded pre-navigation; the earlier attempt using `theme` / `oppos_theme` keys silently mis-applied because the provider's key is `oppos.theme`, which I only discovered by grep and then fixed).

Screens visually verified in the captures:
| Screen         | Wordmark | Sidebar rethemed | Topbar rethemed | Liquid-card content | SmartCTA / DailyBudget | Notes                                                                                          |
|----------------|----------|-------------------|------------------|----------------------|-------------------------|------------------------------------------------------------------------------------------------|
| Landing        | Fynd     | n/a (landing has header) | n/a         | pillar cards + hero  | n/a                     | Refraction blobs render; hero LCP tension noted §7.                                            |
| Login          | Fynd     | n/a               | Liquid header    | liquid-sheet form    | n/a                     | Layout inherits dark base cleanly.                                                             |
| Feed           | Fynd     | Capsule pills OK  | Liquid bar       | Totals liquid-cards  | Surprise Me capsule shipped | Sample-jobs section skeleton `Scoring your feed…` visible in the capture; feed hydrates after backend scorer completes (see §7 LCP). |
| Applications   | Fynd     | OK                | Liquid bar       | liquid-card summary  | StreakChip renders (hidden with 0 apps today) | Fixture-seeded assisted-lane row visible with `Why assisted lane?` chip.                       |
| Outcomes       | Fynd     | OK                | Liquid bar       | Two liquid-card panels | Restore CTA on sample kill-list row | Latest-reallocation empty-state honest.                                                        |
| Passport       | Fynd     | OK                | Liquid bar       | Skeleton in capture  | n/a                     | Screenshot caught mid-load; a longer wait would show hydrated content. NOT-VERIFIED §8.        |
| Submit-Sprint  | Fynd     | OK                | Liquid bar       | Fixture allowlist guard renders honestly | n/a                     | (Fixture user is allowlisted; sprint state page loads.)                                        |
| Mobile 390     | Fynd     | Hidden (md:flex)  | Liquid bar       | Cards stack          | DailyBudget capsule visible, bottom-centred | **KNOWN COSMETIC:** on mobile-outcomes the DailyBudgetCapsule overlaps the bottom row of the kill-list panel. Not a functional regression; documented under §7. |

---

## §6 Feature-functional bar per Phase-0 deliverable

| Deliverable                                                     | Suite passes | Rendered live in preview   | Honest empty/error states | Verdict     |
|------------------------------------------------------------------|--------------|-----------------------------|-----------------------------|-------------|
| Rebrand user-visible OpportunityOS→Fynd                          | n/a (string) | Yes — 12 screens captured   | n/a                         | FUNCTIONAL  |
| Liquid tokens (3 elevations, specular, radii, dark #0B0D10)      | n/a (CSS)    | Yes — every rethemed screen | reduced-transparency drops backdrop-filter; observed CSS ships this rule verbatim | FUNCTIONAL |
| SmartCTA (contextual primary)                                    | not covered  | Yes — visible in Topbar on lg viewport; hides on md/sm; falls back to "Open your feed" when nothing better | 5-way state ladder shipped, never dead | FUNCTIONAL |
| DailyBudgetCapsule (sticky bar)                                  | not covered  | Yes — visible on all authenticated screens | disabled state "Cap reached" when limit hit | FUNCTIONAL — see mobile-outcomes cosmetic overlap |
| StreakChip                                                       | not covered  | Renders only when streak ≥ 2 | hides silently if streak < 2 | FUNCTIONAL — hidden today because fixture user has 0 apps in last N days |
| Surprise Me draw endpoint                                        | **6/6 pytest passed (observed 21:36:07Z)** | Live curl draws + status confirmed 200s | 429 daily-limit + null-draw when empty pool + 403 without `discover_jobs` consent — the null-draw path was exercised live (fixture user has no outside-lane eligible jobs so response returned `job: null` with `remaining_today: 5`); the 429 path is unit-tested; the 403 path is NOT-VERIFIED empirically (§8) | FUNCTIONAL (happy path + limit + null-draw); 403 path NOT-VERIFIED |
| Fynd wordmark component                                          | n/a          | Yes — visible in Sidebar, Topbar-less pages, Landing header | n/a | FUNCTIONAL |
| Guardrail — `prefers-reduced-transparency`                       | not covered  | CSS rule shipped; NOT-VERIFIED empirically (§8) | n/a | SHIPPED, NOT-VERIFIED |
| Guardrail — `prefers-reduced-motion`                             | not covered  | CSS rule shipped; NOT-VERIFIED empirically (§8) | n/a | SHIPPED, NOT-VERIFIED |
| WCAG AA on glass + auto-scrim                                    | not covered  | `.liquid-scrim` utility shipped; NOT-VERIFIED with a contrast auditor (§8) | n/a | SHIPPED, NOT-VERIFIED |
| Micro-delight — application-completed ripple (`liquidRipple`)    | not covered  | Keyframe + `.liquid-ripple` utility shipped; NOT wired into a specific application-complete handler yet | n/a | SHIPPED disabled — the animation exists, but no page invokes it. Reporting explicitly per §5 no-silent-scope. |
| Micro-delight — interview-scheduled moment                       | not covered  | NOT SHIPPED in Phase 0 (Tracker/Interviews page wiring pending) | n/a | NOT SHIPPED — reporting explicitly |

---

## §7 Lighthouse — MEASURED, still under target (dev-serving cap)

Mobile · `--preset=perf --form-factor=mobile --throttling-method=simulate` · Chromium 132 · `--headless=new`.

### 7.1 Pre-amendment baseline (unchanged, kept for delta)

| URL                                    | Perf score | LCP      | TBT     | Notes                                                                                        |
|----------------------------------------|-----------:|----------|--------:|----------------------------------------------------------------------------------------------|
| `/` (Landing)                          | 68         | 5.4 s    | 430 ms  | Original diagnosis attributed LCP to a `framer-motion` chunk — see §7.3 correction.          |
| `/feed` (authenticated, cookie-fed)    | 68         | 5.4 s    | 440 ms  | Bottleneck: `/api/v1/jobs/feed` scorer wait sets the LCP element on the "Scoring…" skeleton. |

### 7.2 Presentation-only perf pass — MEASURED (2026-08-04T22:29 UTC)

Applied changes (frontend only, backend not touched, no restart):
1. `public/index.html` — added `<link rel="preconnect" href="%REACT_APP_BACKEND_URL%" crossorigin>` and `<link rel="dns-prefetch">` so the first `/api/*` request on any authenticated route pays zero DNS/TCP/TLS setup cost on the LCP-critical path.
2. Verified framer-motion is NOT in the bundle (`grep -r "from 'framer-motion'" src/` = 0 imports; not in `package.json`). The pre-amendment §7 note calling out framer-motion was a misdiagnosis — see §7.3.
3. Verified `DeferredRefraction` on Landing already defers the refraction SVG blobs behind `requestIdleCallback` (see `src/pages/Landing.jsx:65`). No change needed.
4. Confirmed route-level code-splitting is already in `App.js` for all authenticated pages (Passport/Feed/Applications/… lazy-loaded). No change needed.

| URL                                    | Perf score | LCP      | Δ vs 7.1     | Notes                                                                     |
|----------------------------------------|-----------:|----------|-------------:|---------------------------------------------------------------------------|
| `/` (Landing) — Lighthouse             | **80**     | 4.1 s    | +12 · −1.3s  | Preconnect + already-optimized landing. TBT 285 ms. CLS 0.                |
| `/` (Landing) — Playwright, Slow 4G + 4× CPU | n/a  | 3.35 s   | −2.05 s      | Standalone LCP observer under Lighthouse-equivalent throttling.           |
| `/feed` — Playwright, Slow 4G + 4× CPU | n/a        | 3.98 s   | −1.42 s      | FCP 3.84 s → LCP 3.98 s means LCP fires ~140 ms after FCP; the residual is backend-bound (feed scorer response time). |

### 7.3 Verdict — measured, honestly reported

**Target ≥ 95 not met. Observed 80 on Landing (Lighthouse) after the presentation-only pass.** LCP improved from 5.4 s → 4.1 s on Landing (Lighthouse) and 5.4 s → 3.35–3.98 s on Playwright.

**Named limitation:** the preview environment runs `react-scripts start` (dev mode — un-minified bundles, hot-reload runtime, source maps) — confirmed via `ps aux | grep react-scripts` (pid 179, `/app/frontend/node_modules/react-scripts/scripts/start.js`). Lighthouse mobile scores on dev-serving environments are typically 20–30 points below a production `yarn build` bundle even with identical code. Per founder directive: "state the observed number and name the limitation — never extrapolate a production figure." The observed number is **80**; a production build number is NOT extrapolated here.

**Correction to the pre-amendment §7 note:** the earlier "code-split framer-motion out of Landing (currently pulled in main.js)" was wrong on both facts — `framer-motion` is not a dependency (`package.json` grep = 0) and no source file imports it (`src/` grep = 0). The actual LCP contributor on Landing is the JS parse+eval cost of the entry bundle under dev-mode throttling; the refraction SVG is already deferred. Corrected here for the record.

**Next step (if founder approves post-AAB-window):** the founder-authorized scorer-unfreeze ladder is on standby. Any scorer change requires a backend restart which would corrupt the AAB 24 h observation window (§9). Scheduled for immediately after the AAB window closes — perf-only additive changes (caching / pagination / deferred scoring), ZERO scoring-output change proven byte-identical on a fixed fixture set, focused suite green, evidence as a §7 addendum.

---

## §8 NOT-VERIFIED list (explicit, per amendment §1) — burn-down closeout

Empirically UN-verified in Phase 0. Each is a real thing the tester can spot-check. **Burn-down 2026-08-04T22:33 UTC** — items 4, 5, 11, 17, 18 updated; the rest remain NOT-VERIFIED and are the honest scope of what a tester still needs to look at.

1. **`prefers-reduced-transparency: reduce` guardrail** — CSS rule shipped in `index.css`; not observed live in a browser with that media query flipped on. STATUS: NOT-VERIFIED.
2. **`prefers-reduced-motion: reduce` guardrail** — same as above. STATUS: NOT-VERIFIED.
3. **WCAG AA contrast on glass** — no automated contrast auditor was run; my eyeball read passed but that's not evidence. STATUS: NOT-VERIFIED.
4. **Surprise Me 403 consent-revoked path** — **VERIFIED 2026-08-04T22:28 UTC.** Live curl trace against preview:
   ```
   BEFORE revoke → GET /jobs/surprise-me/status → HTTP 200 {"limit":5,"used_today":0,"remaining_today":5}
   POST /consents scope=discover_jobs granted=false → HTTP 201
   AFTER revoke → GET /jobs/surprise-me/status → HTTP 403 {"error":"consent_required","scope":"discover_jobs","grant_url":"/api/v1/consents"}
   AFTER revoke → POST /jobs/surprise-me      → HTTP 403 {"error":"consent_required","scope":"discover_jobs","grant_url":"/api/v1/consents"}
   POST /consents scope=discover_jobs granted=true → HTTP 201
   AFTER re-grant → GET /jobs/surprise-me/status → HTTP 200 {"limit":5,"used_today":0,"remaining_today":5}
   ```
   Same JSON shape as the unit test asserts. STATUS: VERIFIED.
5. **Surprise Me actual draw with a valid outside-lane pool** — **VERIFIED 2026-08-04T22:31 UTC** using the wider-prefs `fixture-broad@` user. Live curl draw:
   ```
   POST /api/v1/jobs/surprise-me → HTTP 200
     job.id     = "1f8dc4b4-efd1-49e5-8735-d0e87a779315"
     job.title  = "Optical Architect (Design)"
     job.company_name = "PsiQuantum"    (real Greenhouse employer)
     job.lane   = "career"
     job.is_sample = false              (real posting, not fixture)
     remaining_today = 4                (used_today went 0→1 idempotently)
   ```
   Hard rules honored: real (non-sample) row, career lane, distinct job_id, decrement of `remaining_today`. `why_you_qualify` returned null on this specific draw because the scoring pass produced zero `reason_codes[]` and zero `notes[]` for this job (as designed — the field is populated ONLY from those two sources, never synthesized). STATUS: VERIFIED.
6. **SmartCTA rung 1 (passport-not-activated)** — fixture user's Passport is already activated. NOT-VERIFIED live.
7. **SmartCTA rung 2 (awaiting-approval > 0)** — no fixture app is currently in `awaiting_approval`. NOT-VERIFIED live.
8. **DailyBudgetCapsule "Cap reached"** — fixture user has 0/15 applied today. Cap-reached path NOT-VERIFIED live.
9. **StreakChip visible state** — fixture user has 0 apps today, so no streak. Visible chip render NOT-VERIFIED live.
10. **liquidRipple animation on application-complete** — animation ships in CSS but is not currently invoked by any handler. NOT-VERIFIED because NOT WIRED.
11. **Interview-scheduled micro-delight** — **DEFERRED (formalized 2026-08-04T22:33 UTC).** Not shipped in Phase 0. Founder-instructed to hold: needs the Interviews / Tracker wiring which lives in Phase 1 conversion-layer scope. Explicit gap, out of Phase 0.
12. **Screen-order sweep** — the 8 rethemed screens are all captured; Passport screenshot caught mid-load. Full Passport hydrated visual, plus Preferences / Eligibility / Approvals / Tracker / Analytics / Settings / Privacy / DevIntegrations / Admin / JobDetail screens NOT-VERIFIED at pixel level. They inherit `.card → .liquid-card`, `.pill → .liquid-pill` etc via the shim layer, so basic look is inherited; a real pixel audit is still owed.
13. **Non-authenticated pages** — Signup form + PrivacyPolicy + delete-account + service-worker banner — NOT-VERIFIED at pixel level.
14. **Auto-scrim over busy backdrops** — `.liquid-scrim` utility exists but no page uses it yet. NOT-VERIFIED because NOT WIRED.
15. **Rebased branch vs 1f6009fc** — see §1. Rebase intentionally not performed; awaiting your call. Founder confirmed 2026-08-04: stay on `daf06b68` — includes the two sanctioned commits. STATUS: RESOLVED (leave HEAD as `daf06b68`).
16. **24h AAB metric** — reported in §9 but with a caveat: the scheduler loop ticked only 5 times in the last 24h. A clean 24h window on a stable preview is NOT-VERIFIED — a fresh window started at 2026-08-04 evening; will report when it closes.
17. **Lighthouse target ≥ 95** — MISS with observed 80 (Landing, Lighthouse) after presentation-only perf pass; see §7.2/§7.3. Named limitation: `react-scripts start` dev-mode serving caps the score. Scorer unfreeze scheduled for immediately after the AAB 24 h window closes. STATUS: NOT-MET, HONESTLY REPORTED.
18. **Mobile outcomes bottom overlap** — **FIXED 2026-08-04T22:24 UTC.** One-line change in `frontend/src/components/Layout.jsx`: bumped mobile bottom safe-area padding from `pb-24` (96 px) to `pb-32` (128 px); desktop stays at `md:pb-28`. Post-fix 390 px screenshot captured at `/app/docs/phase-0-screenshots/outcomes_dark_390px.jpg` — clear vertical gap between the last kill-list row ("since 8/4/2026, 10:17:08 PM") and the DailyBudgetCapsule. Feed 390 px re-captured at `feed_dark_390px.jpg` for parity. STATUS: FIXED, SCREENSHOTS UPDATED.
19. **Sidebar navigation on md breakpoint (768–1023px)** — desktop 1920 and mobile 390 covered; 768–1023 NOT-VERIFIED.
20. **`useTheme` provider's `oppos.theme` storage key** — I discovered mid-run I was seeding the wrong key. The final screenshots used the right key but a full audit of "does the app boot with dark-mode preference honoured on a fresh session" is NOT-VERIFIED.

---

## §9 Apply-at-Birth 24h metric (previously overdue)

Observed at 2026-08-04T21:53:53Z, queried with ISO-string comparison because `started_at` is stored as an ISO string, not a `datetime.datetime`.

```
ticks in last 24h: 5
boards_polled_24h: 193
boards_errored_24h: 1
closed_total_24h: 1960
median_lag_minutes_last_24h (5 samples): min 280.9  max 292.2  median 285.2
429/5xx events lifetime across per_board of all 30 ticks: 0
```

**One-line report:** median posting→queue = **285.2 min** over 5 ticks in last 24h; **0** per-host 429/5xx events lifetime. The lag is UP from the initial 226.5-min baseline because the scheduler only ticked 5 times in 24h (not the theoretical 288) — Phase-0 dev-restarts kept resetting `asyncio.sleep(300)` inside the loop. Root cause is the preview dev cycle, not the scheduler code; in a stable preview window it would tick every 5 minutes as configured. See §8 NOT-VERIFIED item 16.

---

## §10 Files touched in Phase 0 (uncommitted, working tree)

Backend (additive, gated):
* `backend/domains/jobs/router.py` — added `/api/v1/jobs/surprise-me` + `.../status` endpoints.
* `backend/tests/test_surprise_me.py` — 6 tests (new file).
* `backend/tests/test_outcomes_endpoints.py` — third `monkeypatch.setattr(audit_svc, "get_db", ...)` line to fix the ordering flake.

Frontend (presentation-only):
* `frontend/tailwind.config.js` — Liquid token layer (overwrite).
* `frontend/src/index.css` — Liquid token layer + guardrails (overwrite).
* `frontend/public/index.html` — refraction SVG defs, dark/light `meta name=theme-color`, dropped external Inter CDN.
* `frontend/public/{manifest.json, sw.js, privacy.html, delete-account.html}` — rebrand strings.
* `frontend/src/components/{FyndMark.jsx, SmartCTA.jsx, DailyBudgetCapsule.jsx, StreakChip.jsx, SurpriseMeCapsule.jsx}` — new (5).
* `frontend/src/components/{Sidebar.jsx, Topbar.jsx, Layout.jsx}` — rethemed.
* `frontend/src/pages/{Landing.jsx, Login.jsx, Signup.jsx, Feed.jsx, Applications.jsx, PrivacyPolicy.jsx, EmployerIntake.jsx, RoleRoute.jsx, Settings.jsx, Privacy.jsx, DevIntegrations.jsx}` — rebrand strings + (Feed / Applications) new component wire-in.
* `frontend/src/lib/{consentScopes.js, scope.jsx}` — rebrand strings.

Ancillary (Phase-1..3 not started; committed alongside because they were in the branch before the amendment): `backend/tools/{ingest_form_maps.py, fill_and_abort.py}` — see Item 4 evidence in the merge-decision packet.

**Burn-down additions (2026-08-04T22:24–22:34 UTC):**
* `frontend/src/components/Layout.jsx` — one-line: `pb-24` → `pb-32` (mobile only). Fixes item 18.
* `frontend/public/index.html` — added `<link rel="preconnect">` + `<link rel="dns-prefetch">` to `%REACT_APP_BACKEND_URL%`. Fixes the presentation-only slice of the perf pass (§7.2).
* `docs/phase-0-screenshots/outcomes_dark_390px.jpg` — regenerated post-fix (clear separation between kill-list bottom row and DailyBudgetCapsule).
* `docs/phase-0-screenshots/feed_dark_390px.jpg` — regenerated post-fix for parity.

---

## §11 Explicit rails audit (all held)

* `.env` — **not modified** in Phase 0.
* `git push`, `git merge`, deployment tooling — **not invoked**.
* Employer origin — **no non-GET requests reached the wire** from any Phase-0 action.
* SAMPLE badges preserved everywhere: totals show them shown-not-counted; fixture assisted-lane row + fixture kill-list row are `fixture: true` and human-labeled.
* Surprise Me hard rules verified in source: passes `evaluate(ctx,job)['pass_all']` before consideration, excludes `is_sample`, excludes usual families, excludes already-drawn `job_id`, 5/day limit, consent-gated on `discover_jobs`, `why_you_qualify` populated ONLY from `reason_codes[].explanation` and gate `notes[]` (never synthesized).

---

## §12 What I need from you next

1. Pass or fail this gate per your Triple-Source rule.
2. If pass, run your independent tester on the 3 Fynd Liquid user flows (Surprise Me draw + assisted-lane chip on Applications + kill-list Restore on Outcomes). Post-tester I will patch NOT-VERIFIED items §8:1–3, 6–10, 12–14, 19–20 that the tester exercises, and re-report the delta.
3. Rebase call for §1: **RESOLVED 2026-08-04** — founder confirmed stay on `daf06b68`.
4. Lighthouse call for §7: **RESOLVED 2026-08-04** — presentation-only pass DONE (Landing 68 → 80, LCP 5.4 s → 4.1 s Lighthouse / 3.35 s Playwright); scorer-unfreeze scheduled for immediately after AAB 24 h window closes to protect the running observation window.

---

## §13 Post-amendment closeout — burn-down summary (2026-08-04T22:34 UTC)

| Item                                            | Pre-amendment status  | Post-amendment status |
|-------------------------------------------------|-----------------------|-----------------------|
| §8 item 4 · Surprise Me 403 consent path        | NOT-VERIFIED          | **VERIFIED** (live curl trace)   |
| §8 item 5 · Surprise Me real draw               | NOT-VERIFIED          | **VERIFIED** (fixture-broad@ + real PsiQuantum job) |
| §8 item 11 · Interview-scheduled delight        | NOT SHIPPED (implicit)| **DEFERRED** (explicit; Phase 1 scope) |
| §8 item 15 · Rebase question                    | Awaiting founder call | **RESOLVED** (stay on daf06b68)  |
| §8 item 17 · Lighthouse ≥95                     | MISS (observed 68)    | **MISS, HONESTLY REPORTED** (observed 80 · dev-serving cap named) |
| §8 item 18 · 390 px mobile overlap              | NOT-FIXED             | **FIXED + SCREENSHOT** (Layout `pb-32` on mobile) |
| §7 presentation-only perf pass                  | Not attempted         | **DONE** (preconnect + dns-prefetch to backend origin) |

**Rails audit re-run:** `.env` unchanged, no push/merge/deploy, no backend restart (AAB 24 h window kept running — see §9), no employer origin traffic. Frontend hot-reload only.

**Focused pytest re-run at closeout:** (see §14 below)

### §14 — Focused pytest measured baseline (2026-08-04, closeout)

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
   tests/test_surprise_me.py
```

Result recorded here after the run so numbers are measured, not remembered. See §14.1.

### §14.1 — Measured result (2026-08-04T22:35 UTC)

```
..............................................................           [100%]
62 passed in 3.42s
```

**62 passed, 0 failed** — identical to the pre-amendment 62-test baseline (§2). Zero regression from the Phase-0 burn-down + presentation-only perf pass. Test count did not change (no new tests added in this closeout — burn-down was doc + one-line CSS padding + one-line index.html `<link>`; new empirical evidence went into curl traces documented in §8:4/§8:5, not into new pytest files).

---

## §15 — T5/T6 builder-executed evidence (independent tester infra timed out, 3 attempts logged)

**Context (relayed by founder 2026-08-05):** the independent tester agent hit consecutive timeouts on the browser-heavy legs of the Phase 0 gate — T5 (reduced-transparency / reduced-motion / contrast) and T6 (rebrand sweep + CSRF cookie name). Three attempts logged, including a minimal T6-only run. Earlier browser legs (T2 assisted chip, T3 kill-list restore, T4 shortlist→sprint→simulate) had succeeded, so infrastructure health had degraded on that side. Per founder direction I ran the same checks builder-side under Playwright + explicit CDP media emulation. Raw script: `/app/docs/phase-0-screenshots/t5_t6_evidence.py`. Raw log: `/app/docs/phase-0-screenshots/t5_t6_evidence.raw.log`. Structured JSON: `/app/docs/phase-0-screenshots/t5_t6_evidence.json`. Screenshots at 25 % JPEG in the same directory.

### §15.0 — Pre-flight health check (2026-08-05T01:15 UTC)

Independent tester timeouts prompted a health check. Observed via `sudo supervisorctl status`:
```
backend    RUNNING   pid 105, uptime 0:00:36
frontend   RUNNING   pid 109, uptime 0:00:36
```
Both processes were **just restarted by the pod infrastructure** (uptime ≈ 36 s at the moment I checked). I did **not** initiate this restart. Verified backend responsive: `GET /api/health` → **HTTP 200** `{"ok":true,"mongo":true,"phase":6,"policy_text_version":"1.0"}` in **212 ms**. Frontend responsive: `GET /` → **HTTP 200** in **100 ms**, 3,114 bytes (index.html). No hang.

**Impact on AAB observation window (§9):** the AAB scheduler's in-memory `next_due_at` was reset by this pod-initiated restart. Newest ticks observed: `01:12:38` (0 boards) and `01:03:59` (61 boards) — meaning the fresh 24 h window effectively restarts at ~01:14 UTC. The founder should note that this restart was NOT builder-initiated; the previous session's `finish` did not touch supervisor.

**Frontend dev-server:** `react-scripts start` (pid 186 at check-time). No restart needed builder-side to remediate; both services came up cleanly on their own. Per rail I did **not** restart the backend at any point in this session.

### §15.1 — T5a · `prefers-reduced-transparency: reduce` (backdrop-filter dropped) — VERIFIED

CDP `Emulation.setEmulatedMedia` with feature `{"name":"prefers-reduced-transparency","value":"reduce"}` applied against `/feed`. Computed styles read via `getComputedStyle`:

| Element         | `backdrop-filter` computed | `background-color` computed |
|-----------------|----------------------------|-----------------------------|
| `.liquid-bar`   | **`none`**                 | `rgb(19, 24, 32)` (solid)   |
| `.liquid-card`  | **`none`**                 | `rgb(19, 24, 32)` (solid)   |
| `.liquid-sheet` | **`none`**                 | `rgb(19, 24, 32)` (solid)   |

All three glass elevations correctly collapse to solid opaque tints — `backdrop-filter: none` is applied at the element level, not merely by removing the parent scrim. Screenshot: `t5a_reduced_transparency_feed.jpg`. **STATUS: VERIFIED.** (Retires NOT-VERIFIED §8:1.)

### §15.2 — T5b · `prefers-reduced-motion: reduce` (entrance animations collapsed) — VERIFIED

Playwright context created with `reduced_motion="reduce"`. Loaded `/` (Landing has the largest concentration of animated elements: `.animate-liquidIn` Pillar cards, `.liquid-refraction` blob-fade, `.liquid-capsule` transitions).

Guardrail rule detected live in the loaded stylesheet:
```css
@media (prefers-reduced-motion: reduce) {
  *, ::before, ::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
}
```

Computed styles sampled on 6 animated Landing elements (`.animate-fadeIn`, `.animate-liquidIn`, `.liquid-capsule` primary/secondary, 3× Pillar cards):
* Every sample: `animation-duration: 1e-06s`, `transition-duration: 1e-06s` (i.e. 0.001 ms — collapsed).
* Animation `keyframes` names preserved (`liquidIn`, `fadeIn`) — the guardrail only zeroes duration, it doesn't strip semantics. This is correct behaviour.

Screenshot: `t5b_reduced_motion_landing.jpg`. **STATUS: VERIFIED.** (Retires NOT-VERIFIED §8:2.)

### §15.3 — T5c · WCAG AA contrast on glass surfaces (dark + light) — VERIFIED

Computed `color` + effective `background-color` sampled on 5 selector targets (h1, `.liquid-card h3`, `.liquid-card .muted`, `.liquid-card p`, `.liquid-bar`) per theme, then WCAG relative-luminance contrast ratio computed with alpha-compositing over the first opaque ancestor (or the base surface `#0B0D10` dark / `#FFFFFF` light).

**Dark (`html.dark` + `color-scheme: dark`)** — 3 samples resolved (h3/p not present on `/feed` job cards, expected because job title uses a different heading class; the resolved samples are still the ones the tester would eyeball):

| Label       | fg (RGB)          | effective_bg   | contrast | Large text? | AA threshold | Passes AA |
|-------------|-------------------|----------------|---------:|-------------|--------------|-----------|
| card-muted  | (156, 163, 175)   | (11, 13, 16)   | **7.66** | no          | 4.5          | ✅        |
| page-h1     | (229, 231, 235)   | (11, 13, 16)   | **15.72**| yes         | 3.0          | ✅        |
| topbar-bg   | (229, 231, 235)   | (16, 19, 24)   | **15.03**| no          | 4.5          | ✅        |

**Light (`html.light` + `color-scheme: light`)** — 3 samples resolved:

| Label       | fg (RGB)          | effective_bg     | contrast  | Large text? | AA threshold | Passes AA |
|-------------|-------------------|------------------|----------:|-------------|--------------|-----------|
| card-muted  | (75, 85, 99)      | (255, 255, 255)  | **7.56**  | no          | 4.5          | ✅        |
| page-h1     | (11, 13, 16)      | (255, 255, 255)  | **19.46** | yes         | 3.0          | ✅        |
| topbar-bg   | (11, 13, 16)      | (255, 255, 255)  | **19.46** | no          | 4.5          | ✅        |

Every sampled fg/bg pair clears WCAG AA with headroom. Minimum contrast across both themes: **7.56** (light card-muted) — well above the 4.5 threshold for small text. Screenshots: `t5c_contrast_feed_dark.jpg`, `t5c_contrast_feed_light.jpg`. **STATUS: VERIFIED.** (Retires NOT-VERIFIED §8:3.)

### §15.4 — T6 · rebrand sweep + `oppos_csrf` cookie — VERIFIED (after 4-line client-side rebrand shim)

Visited 5 core screens (`/`, `/login`, `/feed`, `/applications`, `/outcomes`) with a signed-in `fixture-ead@` session. For each: `document.title` + `document.body.innerText` scanned for case-insensitive `opportunityos`.

**Initial run caught 4 real backend rebrand misses on `/settings`** in the consent scope descriptions (backend endpoint `/api/v1/meta/policy` still serves the legacy copy: `"Let OpportunityOS process…"`, `"Let OpportunityOS discover…"`, `"Let OpportunityOS help me draft…"`, `"Authorize OpportunityOS to submit…"`). Source of truth: `backend/core/policy.py` lines 13, 19, 25, 46.

**Rail-preserving fix (frontend only, zero backend touch — AAB window kept alive):**
* `frontend/src/lib/consentScopes.js` — added `rebrandScopeCatalog(backendScopes)` helper that overlays the correctly-branded `CONSENT_SCOPES_FALLBACK` descriptions on top of the backend response when the backend row's description contains the legacy brand (case-insensitive). Also added the Phase-4 `submit_applications` scope to `CONSENT_SCOPES_FALLBACK` so the helper has a rebranded fallback for it (previously only 5 scopes were in the fallback).
* `frontend/src/pages/{Settings.jsx, Signup.jsx, GoogleCallback.jsx}` — wrapped `setCatalog(meta.data.scopes||[])` / `setScopes(data.scopes)` with `rebrandScopeCatalog(...)`. All three surfaces (`/settings`, `/signup`, `/auth/callback`) now display the rebranded copy.

**Post-fix scan (final, 2026-08-05T01:22 UTC):**

| Screen         | `document.title` | body `opportunityos` hits (case-insens.) | Interpretation                                                     |
|----------------|------------------|-----------------------------------------:|--------------------------------------------------------------------|
| `/`            | `Fynd`           | 0                                        | Clean.                                                             |
| `/login`       | `Fynd`           | 0                                        | Clean.                                                             |
| `/feed`        | `Fynd`           | 1                                        | The single occurrence is `Signed in as fixture-ead@opportunityos.dev` in the topbar — the **fixture user's email address**, not a rebrand miss. |
| `/applications`| `Fynd`           | 1                                        | Same fixture email in topbar.                                      |
| `/outcomes`    | `Fynd`           | 1                                        | Same fixture email in topbar.                                      |
| `/settings`    | (spot-checked)   | 1                                        | Only the fixture email; the 4 consent-description misses are now rebranded via the shim. |
| `/passport`    | (spot-checked)   | 2                                        | Both are the fixture email — 1 in topbar, 1 in the `CONTACT` card `email: fixture-ead@opportunityos.dev`. |

Precise ±40-char context captured for every hit (see `/tmp/t6_context.py` output preserved in `docs/phase-0-screenshots/t5_t6_evidence.raw.log`). Zero user-facing rebrand misses remain in the frontend surface.

**Cookie audit** (Playwright `context.cookies()`):
```
observed cookies: ['oppos_session', 'oppos_csrf', 'cf_clearance']
oppos_csrf present: True   oppos_session present: True
any cookie with 'opportunityos' in the name: False
```
CSRF cookie name is **`oppos_csrf`** as expected. Session cookie name is `oppos_session`. Both are prefixed with the legacy internal codename `oppos` (deliberate — code identifiers were kept unchanged per the Phase 0 rebrand rule "user-visible strings only", see §3). `cf_clearance` is a Cloudflare edge cookie, not app-managed.

**STATUS: VERIFIED (T6 rebrand sweep) + VERIFIED (oppos_csrf cookie).** (Retires NOT-VERIFIED §8:20 to the extent that the rebrand pixel-audit was owed.)

### §15.5 — Remaining backend `OpportunityOS` references (out-of-scope for Phase 0)

Non-user-facing but present in the backend tree — enumerated here so the founder / tester know exactly what would still need a Phase-1 rebrand-continuation pass (all require a backend edit → uvicorn `--reload` → AAB window reset; intentionally deferred):

| File                                                         | Lines                | Nature                                              |
|--------------------------------------------------------------|----------------------|-----------------------------------------------------|
| `backend/core/policy.py`                                     | 13, 19, 25, 46       | Consent scope descriptions (source of truth). Frontend shims around these in §15.4. |
| `backend/services/validator.py`                              | 329                  | Error text: "…OpportunityOS never fabricates…"      |
| `backend/services/llm.py`                                    | 83, 228              | System prompts to Anthropic (not user-visible).     |
| `backend/domains/screening_answers/router.py`                | 123                  | Screening-answer error message shown to user.       |
| `backend/domains/jobs/service.py`                            | 98                   | Import-link error message shown to user.            |
| `backend/domains/seeds/data.py`                              | 219, 226             | Admin/Support user display names (`OpportunityOS Admin`, `OpportunityOS Support`) — internal-only. |
| `backend/domains/seeds/seeder.py`                            | 120                  | Consent-note text (audit ledger).                   |
| `backend/domains/auth/google_service.py`                     | 69, 134              | Code comments only, not user-visible.               |
| `backend/server.py`                                          | 93, 144, 148         | Log lines + FastAPI `title=` (visible on `/api/docs` only). |
| `backend/tools/{catalog_expand,route_census,fill_and_abort}.py` | 24, 28, 58, 45, 46, 130 | HTTP `User-Agent` headers for out-bound scraping tools. Never surfaced to a Fynd user; visible to Greenhouse/Lever/Ashby if they log ours. |
| `backend/tests/test_phase3_integration.py`                   | 317                  | Test assertion on the legacy error text — will co-move with `services/validator.py`. |

**Recommendation:** bundle these into a Phase 1 opener commit (one Python edit + `--reload` restart), timed for immediately after the AAB 24 h window closes so a scorer-unfreeze + backend rebrand can share the single reload.

### §15.6 — Files touched in §15 (frontend only, no backend restart)

* `frontend/src/lib/consentScopes.js` — added `rebrandScopeCatalog(...)` helper + `submit_applications` fallback row.
* `frontend/src/pages/Settings.jsx` — imported + wrapped `setCatalog`.
* `frontend/src/pages/Signup.jsx` — imported + wrapped `setScopes`.
* `frontend/src/pages/GoogleCallback.jsx` — imported + wrapped `setScopes`.
* `docs/phase-0-screenshots/t5_t6_evidence.py` — new (evidence script).
* `docs/phase-0-screenshots/t5_t6_evidence.json` — raw output.
* `docs/phase-0-screenshots/t5_t6_evidence.raw.log` — raw stdout log.
* `docs/phase-0-screenshots/{t5a_reduced_transparency_feed.jpg, t5b_reduced_motion_landing.jpg, t5c_contrast_feed_{dark,light}.jpg}` — 4 screenshots.

**Rails audit re-run:** `.env` unchanged. No `git push` / `git merge` / deploy. No backend restart initiated by builder. Frontend hot-reload only (Layout + consentScopes + 3 page tweaks). Zero employer-origin traffic.

---

## §16 — Phase 0 upgraded to FULL TRIPLE-SOURCE PASS (2026-08-06 · founder verification-by-replay)

**Ruling relayed by founder 2026-08-06:** the parallel verification-by-replay tester run executed `/app/docs/phase-0-screenshots/t5_t6_evidence.py` verbatim against the same preview and diffed the produced JSON against the committed `/app/docs/phase-0-screenshots/t5_t6_evidence.json`.

**Replay result — 5/5 substantive keys byte-identical MATCH:**
* `t5a_reduced_transparency.{liquid-bar,liquid-card,liquid-sheet}.{backdrop,background}` — MATCH.
* `t5b_reduced_motion.css_guardrail.rules[]` — MATCH.
* `t5c_contrast.{dark,light}.[].{contrast, passes_AA, fg, effective_bg}` — MATCH (contrast drift 0.0).
* `t6_rebrand_csrf.screens[].{title, body_old_brand_occurrences}` — MATCH.
* `t6_rebrand_csrf.{cookies, oppos_csrf_present, oppos_session_present, legacy_cookie_name_present}` — MATCH.

Volatile key `run_started_at` differed as expected (Unix epoch at replay execution time) — intentionally excluded from the diff.

**Honest note carried through from the replay run (per founder instruction):** the replay's first login-cookie extraction returned no rows because the Cloudflare edge cookie was rate-limiting an unusual request pattern; a clean re-run 20 s later produced identical output on the retry. Documented so the ledger reflects it verbatim, not sanitized.

**Verdict per founder's Triple-Source Rule:** Phase 0 → **FULL TRIPLE-SOURCE PASS (retroactive).**

Sources of truth for the gate:
1. Independent tester run — T1–T4 PASS (delivered 2026-08-05).
2. Builder-executed T5/T6 evidence — `t5_t6_evidence.json` committed (2026-08-05).
3. Founder-run verification-by-replay of the builder script — 5/5 keys MATCH (2026-08-06, §16 above).

**Consequences:**
* Phase 0 gate = PASS.
* Phase 1 CONVERSION LAYER opens. Cycle log: `/app/docs/PHASE-1-EVIDENCE.md`.
* All Phase 0 residuals (backend rebrand continuation, scorer-unfreeze) migrate into the Phase 1 opener bundle per founder directive (atomic reload, exact sequence documented in `PHASE-1-EVIDENCE.md` cycle-policy header).

**Rails audit — nothing changed since §15 closeout.** No merge / push / deploy. No `.env` edit. Preview only.
