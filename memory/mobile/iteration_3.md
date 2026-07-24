# Iteration 3 — Phase 3: Store compliance, ApplicationPrep, Privacy, Readiness Sweep

## What was implemented

### New screens
- **`app/prep/[applicationId].tsx`** (519 lines) — Full ApplicationPrep workflow
  - Three tabs: Resume, Screeners, Summary
  - Resume tab: regenerate with instruction, base résumé display, tailored résumé with accept/revert per line, validator chip, rejected lines display
  - Screeners tab: answer questions, generate grounded suggestions for non-sensitive, approve toggle for sensitive, save individual answers
  - Summary tab: packet overview, state-specific actions (ready-for-approval, route drawer, submit, attest, receipt card)
  - Complete state machine: shortlisted → preparing → awaiting_approval → approved → submitting → submitted → receipt
  - All interactive elements have unique testIDs
  - AuthGate protected, pull-to-refresh, keyboard-avoiding, back navigation

- **`app/privacy.tsx`** (178 lines) — Privacy & Data management
  - Active consent scopes with revoke buttons
  - Data-release log
  - Export data (notes web download requirement)
  - Account deletion with 30-day soft-delete confirmation
  - AuthGate protected, pull-to-refresh

### Updated screens
- **`app/(tabs)/applications.tsx`** — Added "Open prep →" link for each application row
- **`app/(tabs)/settings.tsx`** — Added "Privacy & Data" navigation link
- **`app/_layout.tsx`** — Registered `prep/[applicationId]` and `privacy` routes in Stack

### Fixes
- **`app/preferences.tsx`** — Fixed TS2345 error by adding explicit type annotation to `DEFAULT_PREFS`
- **`app.json`** — Added `web.splash` configuration for Expo web preview dark background

## Web-to-Mobile mapping decisions
- Web two-column Resume layout → single-column vertical scroll
- Web `<details>` expandable sections → stateful show/hide with chevron
- Web blob download (PDF/DOCX export) → omitted on mobile (web-only); text content viewable inline
- Web clipboard copy → omitted for v1 (could add expo-clipboard later)
- Web `<textarea>` → `<TextInput multiline>`
- Web `<Link to="/approvals">` → `router.push('/approvals')`
- Web `document.cookie` for CSRF → platform-aware in api.ts interceptor (already handled)

## Verification results
- expo-doctor: 18/18 passed
- tsc --noEmit: 0 errors (was 1 error before preferences fix)
- ESLint: 0 issues on all modified files
- expo export: clean 1.58 MB bundle
- Icon raw pixel hash: EXACT MATCH to founder reference
- Routes: both new routes accessible and auth-gated

## Known issues / deferred items
1. **WEB-LANE BLOCKER**: No public unauthenticated privacy policy URL exists. Founder/web team must create one.
2. Web-preview CORS: localhost → preview backend fails with `withCredentials: true`. Documented known limitation.
3. Billing screen: not implemented (out of scope for v1 mobile)
4. Google OAuth native: not implemented (requires native SDK integration, out of scope)
5. Native splash: classified as KNOWN WEB-PREVIEW ARTIFACT. Native launch behavior must be validated on real device.

## Dependencies installed
- None new in Phase 3

## API endpoints used by new screens
- `GET /api/v1/applications/{id}/prep`
- `GET /api/v1/applications/{id}/screeners`
- `POST /api/v1/applications/{id}/prepare`
- `POST /api/v1/applications/{id}/regenerate`
- `POST /api/v1/applications/{id}/resume-lines/{lineId}`
- `POST /api/v1/applications/{id}/ready-for-approval`
- `POST /api/v1/applications/{id}/submit`
- `POST /api/v1/applications/{id}/attest`
- `GET /api/v1/applications/{id}/receipt`
- `POST /api/v1/applications/{id}/screeners/{qid}/answer`
- `POST /api/v1/applications/{id}/screeners/{qid}/generate`
- `GET /api/v1/privacy/consents`
- `GET /api/v1/privacy/release-log`
- `POST /api/v1/privacy/consents/revoke`
- `POST /api/v1/privacy/export`
- `GET /api/v1/privacy/export/{job_id}`
- `POST /api/v1/privacy/account/delete`
