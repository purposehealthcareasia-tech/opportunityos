# Expo App Store Readiness Review — 2026-07-24

**Target:** iOS App "Fyndd" · Bundle ID `com.purposehealthcarelabs.fynd` · Team X2RWXHKTXJ
**Reviewed commit:** `b74d7185` (auto-commit) + working-tree changes in `mobile/.env`, untracked `mobile/yarn.lock`
**Production backend:** `https://fynd.llc`
**Preview backend:** `https://lynk-preview-2.preview.emergentagent.com`

---

## 1. Project Validity

| Check | Result | Evidence |
|-------|--------|----------|
| `package.json` present + valid JSON | **PASS** | Parses, `"main": "expo-router/entry"`, `"private": true` |
| `yarn.lock` present + in sync | **FAIL (git)** | File exists, `yarn check --integrity` passes, but **untracked** — not committed. EAS build will do `yarn install` from scratch without a deterministic lockfile. |
| Expo SDK version | **PASS** | SDK 52 (`expo@52.0.49`). Current supported SDK. |
| Node compatibility | **PASS** | Node 20.20.2, Yarn 1.22.22. EAS Ubuntu builder images ship Node 18/20. |
| `npx expo-doctor` | **FAIL (3 issues)** | ① `.expo/` not git-ignored. ② Missing peer dep `expo-font` (required by `@expo/vector-icons`). ③ `react-native@0.76.7` should be `0.76.9`; `@expo/vector-icons@14.1.0` should be `~14.0.4`. |
| `npx expo export --platform web` | **PASS** | Exported 864 modules → 1.53 MB JS bundle, no errors. |
| TypeScript `tsc --noEmit` | **FAIL (1 error)** | `app/preferences.tsx(46,40): TS2345` — `string` not assignable to `never` (array generic inference bug in `locations` typing). |
| ESLint | **FAIL (14 issues)** | 2 actual errors (unescaped `'` in `passport.tsx` JSX), 12 warnings (unused imports, duplicate imports in `eligibility.tsx`, missing hook deps). |

---

## 2. app.json / app.config

| Check | Result | Evidence |
|-------|--------|----------|
| `expo.name` = "Fyndd" | **FAIL** | Currently `"OpportunityOS"`. |
| `expo.slug` = fyndd-appropriate | **FAIL** | Currently `"opportunityos"`. |
| `ios.bundleIdentifier` = `com.purposehealthcarelabs.fynd` | **FAIL** | Currently `"com.opportunityos.app"`. |
| `ios.buildNumber` present | **FAIL** | Missing entirely. EAS/Xcode requires it. |
| `version` present | **PASS** | `"1.0.0"`. |
| `expo.icon` (1024×1024 PNG) | **FAIL** | Key missing; `assets/` directory is **empty**. |
| `expo.splash` config | **FAIL** | Key missing; no splash image file. |
| `ios.infoPlist` (permissions) | **FAIL** | Key missing. Even without camera/location, Apple still expects `NSAppTransportSecurity` clarity and will flag missing entries if `expo-secure-store` triggers Keychain entitlements. |
| `android.adaptiveIcon.foregroundImage` | **FAIL** | Key missing; no image file. |
| `expo.scheme` | **PASS** | `"opportunityos"` (but should be updated to `"fyndd"` for deep linking). |

---

## 3. .env

| Check | Result | Evidence |
|-------|--------|----------|
| `EXPO_PUBLIC_BACKEND_URL` present | **PASS** | Set to `https://lynk-preview-2.preview.emergentagent.com`. |
| Backend reachable | **PASS** | Both preview and prod (`https://fynd.llc`) respond to API calls. |
| Points at correct backend for prod build | **FAIL** | Currently points at the **preview** URL, not `https://fynd.llc`. The EAS pipeline must substitute this, but the committed (git) `.env` is still the old placeholder with **zero env vars** — EAS will get an empty file unless the pipeline explicitly writes it. |
| No secrets leaked | **PASS** | Only `EXPO_PUBLIC_*` and packager config vars; no API keys or tokens. |
| `EXPO_PACKAGER_HOSTNAME` value | **FAIL (minor)** | Set to `https://lynk-preview-2.preview.emergentagent.com` — this should be a bare hostname or `0.0.0.0`, not a URL. Does not affect EAS builds but indicates leftover from debugging. |

---

## 4. App Completeness — Screen-by-Screen Audit

### Screens that RENDER (verified via localhost:3001 screenshots)

| Screen | Route | Renders | API-connected | Auth-gated | Notes |
|--------|-------|---------|---------------|------------|-------|
| Landing | `/` | ✅ | N/A | No (correct) | Displays "OpportunityOS" branding (should be "Fyndd"). All pillar cards render. |
| Login | `/login` | ✅ | Yes (POST /auth/login) | No (correct) | Form renders. **CORS blocks cookie auth from localhost preview** — login POST returns 200 but `Secure` flag on session cookies prevents browser from storing them. Login is **non-functional in web preview** without backend env tweaks. On native iOS, cookies should work (no CORS). |
| Signup | `/signup` | ✅ | Yes (GET /meta/policy, POST /auth/signup) | No (correct) | Full consent-scope UI renders with all 5 scopes. Same cookie/CORS issue as login. |
| Feed | `(tabs)/feed` | ✅ (auth gate) | Yes | ✅ via tabs `_layout.tsx` | Redirects to `/login` when unauthenticated (correct). Cannot verify authenticated view without live session. |
| Passport | `(tabs)/passport` | ✅ (auth gate) | Yes | ✅ | Same auth gate. |
| Applications | `(tabs)/applications` | ✅ (auth gate) | Yes | ✅ | Same auth gate. |
| Tracker | `(tabs)/tracker` | ✅ (auth gate) | Yes | ✅ | Same auth gate. |
| Settings | `(tabs)/settings` | ✅ (auth gate) | Yes | ✅ | Same auth gate. Nav links to Preferences, Eligibility, Approvals, Analytics. |
| Job Detail | `/jobs/[jobId]` | ✅ | Yes | ❌ **NOT gated** | No auth check — will crash with 401 if accessed directly. |
| Preferences | `/preferences` | ✅ | Yes | ❌ **NOT gated** | Shows "Could not load" (expected for unauth). Should redirect to login. |
| Eligibility | `/eligibility` | ✅ | Yes | ❌ **NOT gated** | Shows "Could not load". Has **duplicate `import { Platform }` at line 93** (after component body). |
| Approvals | `/approvals` | ✅ | Yes | ❌ **NOT gated** | Shows "Failed to load". Daily cap card still renders with defaults. |
| Analytics | `/analyticsScreen` | ✅ | Yes | ❌ **NOT gated** | Shows "Failed to load analytics." |

### Web screens with NO mobile equivalent

| Web Route | Severity | Notes |
|-----------|----------|-------|
| `/applications/:id/prep` (ApplicationPrep) | **HIGH** — core user flow | Resume/cover-letter builder. Critical for the "grounded materials" value prop. |
| `/billing` | MEDIUM | Subscription management. |
| `/privacy` | **HIGH** — App Store requirement | Apple requires accessible privacy policy in-app. |
| `/admin` | LOW | Admin-only; not user-facing. Skip for v1. |
| `/auth/callback` (Google OAuth) | MEDIUM | Google Sign-In flow; web-only redirect pattern needs native equivalent. |

### Auth/Session Architecture Issue (CRITICAL for native iOS)

The backend uses **cookie-based sessions** (`oppos_session` httpOnly cookie + `oppos_csrf` JS-readable cookie). The mobile API client:
- **Web:** Reads CSRF from `document.cookie` — works if CORS + Secure flags are configured.
- **Native iOS:** `withCredentials: true` on `axios` does NOT automatically handle cookies on React Native. React Native's `fetch`/`XMLHttpRequest` polyfill does not implement a cookie jar. **No native cookie/token storage is implemented.** `expo-secure-store` is declared as a plugin but never imported or used anywhere.

**Result:** On a real iOS device, login will POST successfully → cookies are set in the response → subsequent requests will NOT include cookies → every API call returns 401. **The app is completely non-functional on native iOS.**

---

## 5. App Store Submission Requirements

| Requirement | Status | Detail |
|-------------|--------|--------|
| Privacy Policy URL | **FAIL** | No `privacyManifests` in app.json. No `/privacy` screen in mobile app. Apple **will reject** without one. |
| `NSAppTransportSecurity` | **PASS (default)** | No custom ATS config; Expo defaults allow HTTPS. `EXPO_PUBLIC_BACKEND_URL` is HTTPS. OK. |
| Permissions strings (NSCameraUsage etc.) | **N/A** | No camera, location, microphone, or contacts usage detected. No permission strings needed currently. |
| App Tracking Transparency | **FAIL** | No ATT declaration. If no tracking, Apple requires a `NSUserTrackingUsageDescription` absence to be explicitly declared in the privacy manifest. |
| Minimum functionality (Guideline 4.2) | **FAIL — HIGH RISK** | With cookie auth broken on native, the app effectively shows only 3 screens (landing, login form, signup form) before hitting a dead end. Even if auth worked, **ApplicationPrep** (the core resume-builder flow) is missing. Apple routinely rejects apps that are "too simple" or are "a web wrapper with limited native value." The current state would very likely receive a 4.2 rejection. |
| App icon (1024×1024) | **FAIL** | No icon file. EAS build will fail immediately. |
| Launch screen / splash | **FAIL** | No splash config or image. iOS requires a launch storyboard or splash image. |
| `ios.buildNumber` | **FAIL** | Missing. TestFlight/App Store Connect requires it. |

---

## 6. Git Hygiene

| Item | Status | Action Needed |
|------|--------|---------------|
| `mobile/.env` — modified, not committed | **FAIL** | The committed version is the old placeholder (zero env vars). The working-tree version has `EXPO_PUBLIC_BACKEND_URL` + packager vars. **Must be committed** for EAS pipeline to inject the correct backend URL. |
| `mobile/yarn.lock` — untracked | **FAIL** | **Must be committed** for reproducible EAS builds. Without it, `yarn install` on the builder resolves fresh versions, potentially introducing breaks. |
| `mobile/.gitignore` — missing | **FAIL** | `.expo/`, `node_modules/`, `dist/`, `*.tsbuildinfo` should be ignored. `expo-doctor` flagged `.expo/` not being ignored. |
| `mobile/.expo/` directory | **FAIL** | Contains machine-specific state. Should be git-ignored. |

---

## VERDICT: `NOT_READY`

### Blocking Issues (ordered by severity)

| # | Severity | Issue | Impact |
|---|----------|-------|--------|
| 1 | **P0 — SHIP BLOCKER** | **Native auth is completely broken.** No cookie jar / token persistence on iOS. `expo-secure-store` is a plugin but never used. Every API call after login returns 401 on a real device. | App is non-functional on iOS. |
| 2 | **P0 — BUILD BLOCKER** | **No app icon** (1024×1024 PNG). EAS iOS build will fail. | Cannot produce an IPA. |
| 3 | **P0 — BUILD BLOCKER** | **No splash/launch screen** image. | iOS requires it; Xcode build will fail or produce a black launch screen. |
| 4 | **P0 — BUILD BLOCKER** | **Wrong bundle ID.** `com.opportunityos.app` ≠ target `com.purposehealthcarelabs.fynd`. | Signing will fail against the Apple Team certificate. |
| 5 | **P0 — BUILD BLOCKER** | **Missing `ios.buildNumber`** in app.json. | App Store Connect rejects uploads without it. |
| 6 | **P0 — BUILD BLOCKER** | **Missing peer dep `expo-font`** (required by `@expo/vector-icons`). | Native build may crash at launch. |
| 7 | **P0 — REVIEW REJECTION** | **No privacy policy URL or in-app privacy screen.** | Automatic Apple rejection (Guideline 5.1.1). |
| 8 | **P0 — REVIEW REJECTION** | **Guideline 4.2 minimum functionality risk.** Core flow (ApplicationPrep) missing; auth broken; app shows landing + broken login. | Very likely 4.2 "minimum functionality" rejection. |
| 9 | **P1 — BRANDING** | App name, slug, scheme all say "OpportunityOS" instead of "Fyndd". 13+ hardcoded string occurrences. | Wrong app name in App Store listing + user-facing UI. |
| 10 | **P1 — GIT** | `yarn.lock` untracked, `.env` uncommitted, no `.gitignore`. | Non-reproducible EAS builds. |
| 11 | **P2 — CODE QUALITY** | 1 TS error (`preferences.tsx`), 2 ESLint errors, 12 warnings, duplicate import in `eligibility.tsx`. | May cause runtime crashes on strict TS builds. |
| 12 | **P2 — AUTH GATE** | 5 stack screens (job detail, preferences, eligibility, approvals, analytics) have **no auth guard** — accessible as unauthenticated deep links. | Data leak / crash on unauthenticated access. |
| 13 | **P2 — FEATURE GAP** | Missing screens: ApplicationPrep, Billing, Privacy, Google OAuth native flow. | Incomplete feature parity with web. |
| 14 | **P3 — DEPS** | `react-native@0.76.7` should be `0.76.9`. `@expo/vector-icons` version mismatch. | Potential subtle bugs on native. |

---

### Estimated Remaining Work to Reach Buildable, Review-Passing v1

| Work Item | Est. Effort | Dependencies |
|-----------|-------------|--------------|
| Implement native auth (Bearer JWT or cookie-jar via `expo-secure-store` + `@react-native-cookies/cookies`) | 4–6 hrs | Backend must enable JWT issuer OR mobile must implement cookie persistence |
| Create app icon (1024×1024) + splash image + adaptive icon | 1–2 hrs | Design asset from team |
| Fix app.json: name→Fyndd, bundleIdentifier, buildNumber, icon, splash, scheme | 30 min | Icon/splash assets ready |
| Replace all "OpportunityOS" strings with "Fyndd" | 30 min | — |
| Add `expo-font` peer dep, fix RN + vector-icons versions | 15 min | — |
| Add `.gitignore`, commit `yarn.lock` + `.env` | 15 min | — |
| Add auth guards to 5 unprotected stack screens | 30 min | — |
| Build `/privacy` screen (or link to hosted privacy policy URL) | 1 hr | Privacy policy URL from legal |
| Build ApplicationPrep screen (core flow) | 6–10 hrs | Complex screen with resume builder logic |
| Fix TS error, ESLint errors, duplicate import | 30 min | — |
| Add `eas.json` with iOS build profile | 15 min | Apple Team ID + provisioning |
| Test full E2E flow on iOS Simulator / TestFlight | 2–4 hrs | All above complete |
| **Total estimated** | **~16–26 hours** | |
