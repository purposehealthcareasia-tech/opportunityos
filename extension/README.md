# Fynd Capture — Manifest V3 Browser Extension

**Purpose:** Capture the CURRENT job URL for Fynd's Employers Connect
queue. **URL-only.** Never reads page content, never bypasses cookies
or CAPTCHA, never submits anything.

## What it does

1. You click the extension icon on any job posting page.
2. The popup shows the tab's URL.
3. You click **Capture URL** → the URL is POSTed to
   `POST /api/v1/employers/connect` using your logged-in Fynd session
   cookie (via `credentials: "include"`).
4. Fynd's backend runs the URL through the SAME validator + three hard
   gates + 24h cap that the website uses. Verdict returns.

## What it explicitly does not do

- **No DOM reads.** The manifest requests only `activeTab` + `storage`.
  There is no `tabs`, `webNavigation`, or `<all_urls>` permission. No
  content script matches any URL pattern.
- **No page scraping.** URL-only.
- **No auto-submit.** The extension never fills forms, never clicks
  Apply, never bypasses ATS state.
- **No cookie bypass.** Requests use the user's existing browser
  session; no per-site auth is stored in the extension.
- **No CAPTCHA interaction.** Manifest doesn't declare permissions
  needed to interact with pages beyond reading the active tab's URL.

## Blocklist enforced client-side (mirror of backend)

Refused before any POST:
- `linkedin.com` (and `lnkd.in`)
- `indeed.com`
- `handshake.com`, `joinhandshake.com`

Their terms of service don't permit third-party ingestion. Backend
`domains/supply/origin_resolver.py` enforces the same list independently
— a compromised client cannot bypass the server rail.

## Client-side caps

- Hourly cap: 6 captures per rolling hour (UX guard).
- Backend cap: 20 captures per 24h (`_MAX_SUBMISSIONS_PER_24H`).
- 429 responses are logged to the admin abuse trail.

## Install (developer mode)

1. `chrome://extensions` → toggle "Developer mode".
2. "Load unpacked" → point to `/app/extension`.
3. Pin the icon; enter your Fynd API base once in the popup.

## Anti-regression

- Same URL canonicalizer as the backend (`normalizeUrl` in `lib/url.js`
  matches `domains/supply/origin_resolver.py` for tracking-param strip
  + host-lowercase).
- Same host-blocklist as the backend.
- Node-side unit tests planned for the URL lib (post-Phase 5j when
  the frontend build pipeline picks up the extension source).
