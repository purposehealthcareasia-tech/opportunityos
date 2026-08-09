// Shared constants — kept in step with backend/domains/supply/service.py
// (`_MAX_SUBMISSIONS_PER_24H`) and origin_resolver.py's canonicalization.

// Scraped-platform blocklist enforced client-side BEFORE any POST.
// The backend enforces the same list independently — this client check
// exists to give the user immediate feedback and to avoid burning a
// cap-token on a request the server will refuse anyway.
export const PROHIBITED_HOST_SUFFIXES = Object.freeze([
  "linkedin.com",
  "lnkd.in",
  "indeed.com",
  "handshake.com",
  "joinhandshake.com",
]);

// Public path base — the popup expects the current page's origin to
// tell it where the Fynd API lives. We store it in extension storage
// so the user only has to enter it once. Default: prompt on first use.
export const STORAGE_KEY_API_BASE = "fynd_api_base";

// Hard client-side cap so the popup can't be spammed. The server has
// its own 20/24h cap; this is a UX guard.
export const CLIENT_SIDE_HOURLY_CAP = 6;
export const STORAGE_KEY_RECENT_CAPTURES = "fynd_recent_captures";
