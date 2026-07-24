## Iteration 1 — Phase 1: P0 native auth fix
- **Commit**: e4a3d3fd
- **Date**: 2026-07-24
- **Changes**:
  - Created `src/lib/session.ts` — cross-platform session store (expo-secure-store on native, browser cookies on web)
  - Rewrote `src/lib/api.ts` — platform-aware axios interceptors (Cookie header + CSRF on native, withCredentials on web)
  - Rewrote `src/lib/auth.tsx` — captures session from login/signup responses, hydrates from secure-store on boot
  - Created `src/components/AuthGate.tsx` — reusable auth guard component
  - Wrapped 5 unguarded stack screens with AuthGate (jobs/[jobId], preferences, eligibility, approvals, analyticsScreen)
  - Added auto-redirect on login.tsx and signup.tsx for already-authenticated users
  - Fixed duplicate Platform import in eligibility.tsx
  - Fixed unused imports in approvals.tsx and eligibility.tsx
  - Fixed tabs layout useEffect dependency array
  - Committed mobile/.env and mobile/yarn.lock for reproducible EAS builds
- **Files modified**: 14 (see commit)
- **Web files referenced**: frontend/src/lib/api.js, frontend/src/lib/auth.jsx, frontend/src/components/ProtectedRoute.jsx

## Iteration 1.1 — Micro-fix: backend URL for external testers
- **Commit**: ef149141
- **Date**: 2026-07-24
- **Changes**: EXPO_PUBLIC_BACKEND_URL → https://lynk-preview-2.preview.emergentagent.com (was localhost:8001)

## Iteration 2 — Phase 2: Build config / assets / branding
- **Commits**: 6629d6b3 (assets), 63f98408 (config+branding), 91d8780f (deps/gitignore)
- **Date**: 2026-07-24
- **Changes**:
  - Rasterized founder's Match Lens SVG → 4 asset files (icon.png 1024×1024 RGB no-alpha, icon-light.png, adaptive-icon.png, splash-icon.png)
  - app.json: name=Fynd, slug=fynd, scheme=fynd, bundleIdentifier=com.purposehealthcarelabs.fynd, buildNumber=1, android.package, icon/splash/adaptiveIcon/favicon configured
  - Rebranded all "OpportunityOS" → "Fynd" in index.tsx, signup.tsx, consentScopes.ts, package.json (logo letter O→F, version label v1.0)
  - Added .gitignore, expo-font peer dep, pinned react-native@0.76.9 + @expo/vector-icons@~14.0.4
  - Removed .expo/ from git tracking
  - expo-doctor: 18/18 pass, expo export: clean
- **Files modified**: 10 files, 4 new assets

## Iteration 3 — Phase 3: ApplicationPrep, Privacy, store compliance sweep
- **Commit**: 26e5a2ab
- **Date**: 2026-07-24
- **Changes**:
  - Created `app/prep/[applicationId].tsx` — full ApplicationPrep workflow (3 tabs: Resume, Screeners, Summary; complete state machine; all testIDs)
  - Created `app/privacy.tsx` — Privacy & Data management (consent scopes, release log, export, delete account)
  - Fixed `preferences.tsx` TypeScript TS2345 error (explicit DEFAULT_PREFS type annotation)
  - Added "Open prep →" link in applications list
  - Added "Privacy & Data" nav link in settings
  - Registered prep/[applicationId] and privacy routes in root layout
  - Added web.splash.backgroundColor to app.json
  - Classified Expo web splash as KNOWN WEB-PREVIEW ARTIFACT
  - Icon raw pixel hash: EXACT MATCH (9c46c21b…)
  - Privacy URL: documented WEB-LANE BLOCKER (no public unauthenticated route)
  - Created readiness sweep closure table: phase3_readiness_sweep.md
  - expo-doctor: 18/18, tsc: 0 errors, ESLint: 0 issues, export: clean
- **Files modified**: 7 (2 new, 5 modified)
- **Web files referenced**: frontend/src/pages/ApplicationPrep.jsx, frontend/src/pages/Applications.jsx, frontend/src/pages/Privacy.jsx, frontend/src/lib/api.js
