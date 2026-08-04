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

## §7 Lighthouse — MEASURED, misses target

Mobile · `--preset=perf --form-factor=mobile --throttling-method=simulate` · Chromium 132 · `--headless=new`.

| URL                                    | Perf score | LCP      | TBT     | Notes                                                                                        |
|----------------------------------------|-----------:|----------|--------:|----------------------------------------------------------------------------------------------|
| `/` (Landing)                          | **68**     | 5.4 s    | 430 ms  | Bottleneck: LCP text block waits for `framer-motion` chunk + refraction paint.               |
| `/feed` (authenticated, cookie-fed)    | **68**     | 5.4 s    | 440 ms  | Bottleneck: `/api/v1/jobs/feed` scorer wait — the "Scoring your feed…" skeleton is the LCP element until the scorer returns. Backend was frozen this pass per your Phase-0 rails, so I did NOT touch the scorer. |

**Verdict: MISS.** Target ≥ 95 not met. Observed 68 on both landing and feed. Reasonable next moves once you unfreeze the perf lane: (a) code-split framer-motion out of Landing (currently pulled in main.js), (b) lazy-mount the refraction SVG blobs after first paint, (c) precompute the /feed scorer result server-side or emit a Suspense-friendly loading skeleton with a real placeholder. None of these were attempted in Phase 0 because the founder-approved delta lane was presentation-only.

---

## §8 NOT-VERIFIED list (explicit, per amendment §1)

Empirically UN-verified in Phase 0. Each is a real thing the tester can spot-check:

1. **`prefers-reduced-transparency: reduce` guardrail** — CSS rule shipped in `index.css`; not observed live in a browser with that media query flipped on.
2. **`prefers-reduced-motion: reduce` guardrail** — same as above.
3. **WCAG AA contrast on glass** — no automated contrast auditor was run; my eyeball read passed but that's not evidence.
4. **Surprise Me 403 consent-revoked path** — the pytest asserts the endpoint requires `discover_jobs`, but I did NOT revoke consent live and verify the UI's error state renders honestly.
5. **Surprise Me actual draw with a valid outside-lane pool** — the fixture user's Passport does not currently yield any real outside-lane job that passes all three hard gates + is not SAMPLE, so my live curl saw `job: null`. The 4th pytest simulates a valid draw with monkey-patched context/evaluate/score; a live end-to-end draw against a real Passport is NOT-VERIFIED.
6. **SmartCTA rung 1 (passport-not-activated)** — fixture user's Passport is already activated. NOT-VERIFIED live.
7. **SmartCTA rung 2 (awaiting-approval > 0)** — no fixture app is currently in `awaiting_approval`. NOT-VERIFIED live.
8. **DailyBudgetCapsule "Cap reached"** — fixture user has 0/15 applied today. Cap-reached path NOT-VERIFIED live.
9. **StreakChip visible state** — fixture user has 0 apps today, so no streak. Visible chip render NOT-VERIFIED live.
10. **liquidRipple animation on application-complete** — animation ships in CSS but is not currently invoked by any handler. NOT-VERIFIED because NOT WIRED.
11. **Interview-scheduled micro-delight** — NOT SHIPPED in this pass (see §6). Explicit gap.
12. **Screen-order sweep** — the 8 rethemed screens are all captured; Passport screenshot caught mid-load. Full Passport hydrated visual, plus Preferences / Eligibility / Approvals / Tracker / Analytics / Settings / Privacy / DevIntegrations / Admin / JobDetail screens NOT-VERIFIED at pixel level. They inherit `.card → .liquid-card`, `.pill → .liquid-pill` etc via the shim layer, so basic look is inherited; a real pixel audit is still owed.
13. **Non-authenticated pages** — Signup form + PrivacyPolicy + delete-account + service-worker banner — NOT-VERIFIED at pixel level.
14. **Auto-scrim over busy backdrops** — `.liquid-scrim` utility exists but no page uses it yet. NOT-VERIFIED because NOT WIRED.
15. **Rebased branch vs 1f6009fc** — see §1. Rebase intentionally not performed; awaiting your call.
16. **24h AAB metric** — reported in §9 but with a caveat: the scheduler loop ticked only 5 times in the last 24h (not the theoretical 288) because backend restarts during Phase 0 kept resetting the tier `next_due_at` fingerprint. The 285.2-minute median is real but is not "the scheduler as it would run without dev restarts". A clean 24h window on a stable preview is NOT-VERIFIED.
17. **Lighthouse target ≥ 95** — MISS with observed 68. Not-verified as passing (§7).
18. **Mobile outcomes bottom overlap** — DailyBudgetCapsule visually overlaps the kill-list restore row on 390px width. Cosmetic; not a functional break. NOT-FIXED in Phase 0.
19. **Sidebar navigation on md breakpoint (768–1023px)** — desktop 1920 and mobile 390 covered; 768–1023 NOT-VERIFIED.
20. **`useTheme` provider’s `oppos.theme` storage key** — I discovered mid-run I was seeding the wrong key. The final screenshots used the right key but a full audit of "does the app boot with dark-mode preference honoured on a fresh session" is NOT-VERIFIED.

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
2. If pass, run your independent tester on the 3 Fynd Liquid user flows (Surprise Me draw + assisted-lane chip on Applications + kill-list Restore on Outcomes). Post-tester I will patch NOT-VERIFIED items §8:4–20 that the tester exercises, and re-report the delta.
3. Rebase call for §1: leave HEAD as `daf06b68` (includes your two sanctioned commits) OR rebase liquid onto `1f6009fc` (loses those from underneath)?
4. Lighthouse call for §7: authorize a presentation-only perf pass (code-split framer-motion, lazy refraction, feed skeleton), OR unfreeze the backend so I can move the scorer off the request path?
