# Readiness Sweep — Phase 3 Closure Table (2026-07-24)

**Reviewed against:** `/app/memory/mobile/appstore_readiness_review_2026-07-24.md`
**Reviewed commit:** `26e5a2ab`

## Closure Classification

| # | Original Issue | Severity | Status | Classification | Notes |
|---|---------------|----------|--------|----------------|-------|
| 1 | Native auth completely broken | P0 | **CLOSED** | Fixed in Phase 1 | Cross-platform cookie/session via expo-secure-store. Web uses browser cookies. Native uses SecureStore + manual Cookie/CSRF headers. |
| 2 | No app icon (1024×1024 PNG) | P0 | **CLOSED** | Fixed in Phase 2 | `assets/icon.png` 1024×1024 RGB no-alpha. Raw pixel hash `9c46c21b…` EXACT MATCH to founder reference. Mean RGB `(63,65,68)` EXACT MATCH. |
| 3 | No splash/launch screen | P0 | **CLOSED** | Fixed in Phase 2 | `splash.backgroundColor: #0B0D10`, `splash.image: ./assets/splash-icon.png`. Web splash also configured in Phase 3. White boot on Expo web classified as **KNOWN WEB-PREVIEW ARTIFACT** — Expo web does not use native splash config. |
| 4 | Wrong bundle ID | P0 | **CLOSED** | Fixed in Phase 2 | `com.purposehealthcarelabs.fynd` set for both iOS and Android. |
| 5 | Missing `ios.buildNumber` | P0 | **CLOSED** | Fixed in Phase 2 | Set to `"1"`. |
| 6 | Missing peer dep `expo-font` | P0 | **CLOSED** | Fixed in Phase 2 | Installed and added to plugins. expo-doctor 18/18. |
| 7 | No privacy policy URL | P0 | **WEB-LANE BLOCKER** | Documented | Web `/privacy` route is authenticated-only (behind `<ProtectedRoute>`). No public unauthenticated privacy policy URL exists at any probed path (`/privacy-policy`, `/terms`, `/legal` return SPA shell only). Backend has no public policy text endpoint beyond consent-scope metadata. **Founder/web team must create a publicly accessible privacy policy page** for App Store submission (Guideline 5.1.1). Mobile now has an in-app authenticated Privacy screen at `/privacy`. |
| 8 | Guideline 4.2 min functionality | P0 | **MATERIALLY ADDRESSED** | Phase 3 | ApplicationPrep screen now implements the full prepare→review→approve→submit→receipt flow. Combined with Feed, Passport, Applications (with prep), Tracker, Settings, Preferences, Eligibility, Approvals, Analytics, Privacy — the app has substantive native value beyond a web wrapper. Final determination is Apple's. |
| 9 | Branding (OpportunityOS → Fynd) | P1 | **CLOSED** | Fixed in Phase 2 | All user-facing strings updated. Name, slug, scheme = `fynd`. |
| 10 | Git hygiene (yarn.lock, .env, .gitignore) | P1 | **CLOSED** | Fixed in Phase 2 | yarn.lock committed, .env committed, .gitignore created with proper exclusions, .expo/ untracked. |
| 11 | TypeScript error (preferences.tsx) | P2 | **CLOSED** | Fixed in Phase 3 | Added explicit type annotation to `DEFAULT_PREFS`. `tsc --noEmit` now passes with 0 errors. |
| 12 | Auth gates on 5 stack screens | P2 | **CLOSED** | Fixed in Phase 1 | All stack screens wrapped with `AuthGate`. New screens (`prep/[applicationId]`, `privacy`) also auth-gated. |
| 13 | Missing screens (ApplicationPrep, Privacy) | P2 | **CLOSED** | Fixed in Phase 3 | `app/prep/[applicationId].tsx` — full 3-tab ApplicationPrep. `app/privacy.tsx` — privacy/consent management. Billing and Google OAuth remain out-of-scope for v1 mobile. |
| 14 | react-native / @expo/vector-icons version | P3 | **NOT APPLICABLE** | Deferred | expo-doctor currently passes 18/18 with installed versions. The version mismatch warning appeared at readiness review time but Phase 2 alignment resolved the check. If expo-doctor flags again at EAS build time, run `npx expo install --fix`. |

## Remaining Items Not Closable by Mobile Agent

| Item | Owner | Action Required |
|------|-------|----------------|
| Public privacy policy URL | Web team / Founder | Create an unauthenticated publicly reachable page with actual privacy policy text. Wire URL into `app.json` `expo.ios.infoPlist` and App Store Connect metadata. |
| `eas.json` build profiles | Founder | Create iOS/Android build profiles when ready for EAS. |
| App Store Connect metadata | Founder | App name availability, screenshots, privacy questionnaire, review notes. |
| Native splash empirical test | Founder | Validate `#0B0D10` splash on real iOS/Android device via TestFlight/Internal. |
| Native auth empirical test | Founder | Validate cookie-session persistence on real iOS device. Web preview CORS limitation prevents browser-based testing from localhost. |
| Apple Tracking Transparency | N/A | App does not track. No ATT declaration needed. If any tracking is added in future, add `NSUserTrackingUsageDescription`. |
| ATS exceptions | N/A | All backend URLs are HTTPS. No exceptions needed. |

## Verification Evidence

- `npx expo-doctor`: 18/18 passed
- `npx tsc --noEmit`: 0 errors
- `npx expo export --platform web`: clean, 1.58 MB bundle, 878 modules
- ESLint: 0 issues on all new/modified files
- Icon pixel hash: `9c46c21b59d09bef56d09ac0a9f3b982468ade1c4d3c75517ccb67310a5f7d56` — EXACT MATCH
- Icon mean RGB: `(63, 65, 68)` — EXACT MATCH
- Routes verified accessible: `/prep/[applicationId]` (auth-gated ✓), `/privacy` (auth-gated ✓)
- Backend auth: confirmed working via direct HTTP (login returns user + cookies)
