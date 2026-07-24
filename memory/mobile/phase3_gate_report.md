# Phase 3 Gate Report — Fynd Mobile

**Date:** 2026-07-24  
**HEAD:** `cfd81240fd65e034b2c0d217963a4a85296fed0d`  
**Scope:** `/app/mobile` only — zero changes to `/app/backend`, `/app/frontend`, or their `.env` files.

---

## (a) Builder Evidence — Exact Values, Codes, Commits

### Item 0a — Splash Disposition

| Check | Value |
|-------|-------|
| `app.json splash.backgroundColor` | `#0B0D10` ✓ |
| `app.json splash.image` | `./assets/splash-icon.png` ✓ (file exists, 8358 bytes) |
| `app.json web.splash.backgroundColor` | `#0B0D10` ✓ (added in Phase 3) |
| Classification | **KNOWN WEB-PREVIEW ARTIFACT** — Expo web does not render native splash screen config. The native splash (`#0B0D10` dark background with icon) is correctly configured but requires TestFlight/device to validate empirically. Added `web.splash` config as trivial mitigation for web preview. |
| Commit | `26e5a2ab` |

### Item 0b — Icon Pixel Cross-Check

| Metric | Computed | Reference | Match |
|--------|----------|-----------|-------|
| Image size | 1024×1024 RGB | — | ✓ |
| Raw pixel SHA-256 | `9c46c21b59d09bef56d09ac0a9f3b982468ade1c4d3c75517ccb67310a5f7d56` | `9c46c21b59d09bef56d09ac0a9f3b982468ade1c4d3c75517ccb67310a5f7d56` | **EXACT** |
| Mean RGB (1×1 resize) | `(63, 65, 68)` | `(63, 65, 68)` | **EXACT** |
| Delta | `(0, 0, 0)` | — | Zero |

**Verdict:** Identical raster. No anti-aliasing variance. No fix needed.

### Phase 3.1 — Privacy Policy URL

| Probe | HTTP Status | Result |
|-------|-------------|--------|
| `GET /privacy` on web domain | 200 | Returns SPA HTML shell (index.html), but React route is inside `<ProtectedRoute>` — browser redirects to login. Not publicly accessible. |
| `GET /legal/privacy` | 200 | Same SPA shell, no dedicated route. |
| `GET /privacy-policy` | 200 | Same SPA shell, no dedicated route. |
| `GET /api/v1/meta/policy` (backend) | 200 | Returns JSON consent-scope metadata, not a privacy policy document. |

**Classification:** **WEB-LANE BLOCKER**  
**Reason:** No publicly accessible, unauthenticated privacy policy page exists. Apple Guideline 5.1.1 requires a privacy policy URL accessible without login.  
**Minimal web-lane fix proposal:** Create a public `/privacy-policy` route in the web frontend (outside `<ProtectedRoute>`) that renders static privacy policy text, or serve a static HTML page at that path. Mobile agent cannot implement this (scope lock).  
**Mobile-side wiring done:** In-app authenticated Privacy & Data screen at `/privacy` (consent management, data export, account deletion). Settings screen has "Privacy & Data" navigation link.

### Phase 3.2 — ApplicationPrep Flow

| Component | Evidence |
|-----------|----------|
| File | `app/prep/[applicationId].tsx` — 787 lines |
| Route | `/prep/{applicationId}` via Expo Router Stack |
| Auth | AuthGate-protected |
| Tabs | Resume, Screeners, Summary |
| Resume tab | Regenerate with instruction + refusal handling, base resume display, tailored resume with per-line accept/revert, validator chip, rejected lines |
| Screeners tab | Answer text input, sensitive badge + approval toggle, AI suggest for non-sensitive, save per question |
| Summary tab | Packet overview grid, preparing→ready-for-approval, awaiting_approval→approvals link, approved→route drawer→start submit, submitting→materials hash + attest, submitted→receipt card |
| State machine | shortlisted → preparing → awaiting_approval → approved → submitting → submitted → receipt |
| Error states | consent_required, application_not_found, sensitive_screener_gate, state_precondition_failed, duplicate_application |
| Navigation | "Open prep →" link added to every application card in Applications tab |
| API endpoints | 11 backend endpoints exercised (see iteration_3.md for full list) |
| testIDs | All interactive elements have unique testIDs |
| Commit | `26e5a2ab` |

### Phase 3.3 — Readiness Sweep

See full closure table: `/app/memory/mobile/phase3_readiness_sweep.md`

| Category | Count |
|----------|-------|
| CLOSED | 10 items (#1-6, #9-12) |
| WEB-LANE BLOCKER | 1 item (#7 privacy URL) |
| MATERIALLY ADDRESSED | 1 item (#8 Guideline 4.2) |
| NOT APPLICABLE | 1 item (#14 version mismatch) |

### Phase 3.4 — Verification Matrix

| Check | Result |
|-------|--------|
| `npx expo-doctor` | 18/18 passed |
| `npx tsc --noEmit` | 0 errors |
| ESLint (prep, privacy) | 0 issues |
| `npx expo export` | Clean (exit 0) |
| Landing page screenshot | Renders "Fynd" branding correctly |
| Login page screenshot | Form renders correctly |
| `git diff HEAD -- backend/ frontend/` | Empty (untouched) |
| `.env` diff | Unchanged since Phase 1 |

---

## (b) Independent Tester Checks — Expo Web Preview

The Expo web preview URL is `https://expo-lynk-preview-2.preview.emergentagent.com`.

**Unauthenticated checks (no login required):**

1. **Landing page loads** — verify "Fynd" branding, "Create your account" and "I already have one" buttons, three value-prop cards.
2. **Login page** — navigate to `/login`, verify form with Email/Password fields and "Sign in" button.
3. **Signup page** — navigate to `/signup`, verify form with Email/Password/Name fields, consent scope checkboxes.
4. **Dark web background** — confirm page background is NOT pure white (should be `#0B0D10` or dark per web.splash config). Note: initial flash may still be white due to JS hydration delay.
5. **Navigation** — "Back to home" links on login/signup return to landing.
6. **Auth guard** — navigating directly to `/feed`, `/applications`, `/prep/test123`, `/privacy` should redirect to login.

**Authenticated checks (CORS/cookie limitation on preview edge):**
> Browser-based credentialed login may fail on the Expo web preview due to CORS/proxy behavior (the preview edge rewrites Origin headers). This is a known limitation. The following checks require a direct-localhost or native device session.

7. **Applications list** — each card shows "Open prep →" link.
8. **ApplicationPrep** — tap "Open prep →", verify 3-tab layout (Resume, Screeners, Summary).
9. **Privacy screen** — navigate from Settings → Privacy & Data, verify consent scopes and data controls.
10. **Settings screen** — verify Privacy & Data link is present alongside Preferences/Eligibility/Approvals/Analytics.

---

## (c) MANDATORY NOT-VERIFIED List

These items cannot be verified in the current environment and require native device/TestFlight/founder action:

| # | Item | Reason | Required Action |
|---|------|--------|-----------------|
| 1 | **Native splash launch screen** | Expo web doesn't render native splash. `#0B0D10` config is correct but untested on iOS/Android. | TestFlight or `expo start --dev-client` on real device. |
| 2 | **Native auth cookie persistence** | SecureStore + manual Cookie headers untested on real iOS/Android. Web preview uses browser cookies which face CORS edge limitation. | TestFlight session persistence test: login → kill app → reopen → verify session. |
| 3 | **App icon in native context** | Raw pixel hash matches reference, but actual iOS/Android icon rendering (rounded corners, adaptive icon) is untested. | EAS build → visual inspect on home screen. |
| 4 | **EAS build success** | No `eas build` attempted per scope lock. | Founder runs `npx eas build --platform all`. |
| 5 | **App Store name availability** | "Fynd" availability in App Store Connect is founder-side. | Check via App Store Connect. |
| 6 | **Public privacy policy URL** | **WEB-LANE BLOCKER.** No unauthenticated page exists. Required for App Store submission (Guideline 5.1.1). | Web team creates public `/privacy-policy` route. |
| 7 | **Expo web preview authenticated login** | CORS/proxy edge rewriting blocks `withCredentials: true` from external browser. Login returns cookies but browser may not store them cross-origin. | Known web preview limitation. Test on localhost or native. |
| 8 | **ApplicationPrep with real data** | Backend returns prep packet for authenticated user with applications. Cannot create test fixtures in current scope. | Login with test user who has shortlisted/preparing applications. |
| 9 | **Privacy screen with real data** | Consent scopes and release log require authenticated session. | Login with test user. |
| 10 | **Apple Tracking Transparency** | App does not track. No ATT required. If tracking is added later, must add `NSUserTrackingUsageDescription`. | N/A unless tracking is introduced. |
| 11 | **App Transport Security** | All URLs are HTTPS. No ATS exceptions needed. | N/A. |

---

## (d) Git State Footer

```
HEAD commit:  cfd81240fd65e034b2c0d217963a4a85296fed0d
Parent:       26e5a2abe04d8e9c1c446ced812205fb9cc62e5d
Branch:       main (ahead of origin by 65 commits)
Working tree: clean (zero uncommitted changes)

Phase 3 commits:
  26e5a2ab  feat(mobile): Phase 3 — ApplicationPrep screen, Privacy screen, splash/icon/TS fixes
  cfd81240  docs(mobile): Phase 3 iteration memory, readiness sweep, commit log

Scope confirmation:
  - git diff HEAD -- backend/   → empty (untouched)
  - git diff HEAD -- frontend/  → empty (untouched)
  - mobile/.env                 → unchanged since Phase 1 (ef149141)
  - No new dependencies installed in Phase 3
  - No EAS builds attempted
  - supervisor: only mobile was restarted

Files added/modified (Phase 3 only):
  NEW:  mobile/app/prep/[applicationId].tsx  (787 lines)
  NEW:  mobile/app/privacy.tsx               (203 lines)
  MOD:  mobile/app.json                      (web.splash added)
  MOD:  mobile/app/_layout.tsx               (+2 Stack.Screen registrations)
  MOD:  mobile/app/(tabs)/applications.tsx   ("Open prep" link)
  MOD:  mobile/app/(tabs)/settings.tsx       ("Privacy & Data" nav link)
  MOD:  mobile/app/preferences.tsx           (TS type fix)
  NEW:  memory/mobile/commit_log.md          (appended)
  NEW:  memory/mobile/iteration_3.md
  NEW:  memory/mobile/phase3_readiness_sweep.md
```
