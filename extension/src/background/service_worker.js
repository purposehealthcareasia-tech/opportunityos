// Service worker — extremely thin.
//
// Responsibilities (rails):
//   1. Persist recent-capture timestamps for client-side hourly cap.
//   2. Expose a `POST_CAPTURE` message handler that the popup calls
//      after user-click. The service worker performs the actual fetch
//      to /api/v1/employers/connect (with credentials) and returns the
//      server's verdict. It does NOT retry or open any tab.
//   3. NO permissions beyond `activeTab` + `storage`. No host
//      permissions in manifest → we cannot inject content scripts,
//      cannot read page DOM, cannot bypass cookies.

import {
  STORAGE_KEY_RECENT_CAPTURES,
  CLIENT_SIDE_HOURLY_CAP,
} from "../lib/constants.js";
import { isProhibitedHost, isHttpsUrl, normalizeUrl } from "../lib/url.js";

async function _readRecent() {
  const r = await chrome.storage.local.get([STORAGE_KEY_RECENT_CAPTURES]);
  return Array.isArray(r[STORAGE_KEY_RECENT_CAPTURES]) ? r[STORAGE_KEY_RECENT_CAPTURES] : [];
}

async function _writeRecent(list) {
  await chrome.storage.local.set({ [STORAGE_KEY_RECENT_CAPTURES]: list });
}

async function _checkClientSideCap() {
  const now = Date.now();
  const oneHourAgo = now - 60 * 60 * 1000;
  const recent = (await _readRecent()).filter((ts) => ts >= oneHourAgo);
  if (recent.length >= CLIENT_SIDE_HOURLY_CAP) {
    return { over_cap: true, count: recent.length, cap: CLIENT_SIDE_HOURLY_CAP };
  }
  return { over_cap: false, count: recent.length, cap: CLIENT_SIDE_HOURLY_CAP };
}

async function _recordCapture() {
  const now = Date.now();
  const oneHourAgo = now - 60 * 60 * 1000;
  const recent = (await _readRecent()).filter((ts) => ts >= oneHourAgo);
  recent.push(now);
  await _writeRecent(recent);
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "POST_CAPTURE") {
    (async () => {
      const { apiBase, rawUrl } = msg;
      // Client rail 1: https-only.
      if (!isHttpsUrl(rawUrl)) {
        sendResponse({ ok: false, verdict: "client_reject", reason: "not_https" });
        return;
      }
      // Client rail 2: prohibited hosts.
      if (isProhibitedHost(rawUrl)) {
        sendResponse({ ok: false, verdict: "client_reject", reason: "blocked_host" });
        return;
      }
      // Client rail 3: hourly cap.
      const cap = await _checkClientSideCap();
      if (cap.over_cap) {
        sendResponse({ ok: false, verdict: "client_reject",
                        reason: "client_hourly_cap",
                        recent_count: cap.count, cap: cap.cap });
        return;
      }
      // Normalize + POST. Credentials include for the user's session cookie.
      const normalized = normalizeUrl(rawUrl);
      let resp;
      try {
        resp = await fetch(`${apiBase.replace(/\/$/, "")}/api/v1/employers/connect`, {
          method: "POST",
          credentials: "include",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ url: normalized }),
        });
      } catch (e) {
        sendResponse({ ok: false, verdict: "network_error", detail: String(e) });
        return;
      }
      let body = null;
      try { body = await resp.json(); } catch (_) { body = null; }
      if (resp.ok) {
        await _recordCapture();
      }
      sendResponse({ ok: resp.ok, status: resp.status, verdict: "server", body });
    })();
    return true;  // keep the message channel open for async sendResponse
  }
  return false;
});
