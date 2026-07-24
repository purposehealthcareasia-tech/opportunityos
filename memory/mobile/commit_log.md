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
