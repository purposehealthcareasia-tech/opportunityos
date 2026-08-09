// Popup script — reads the active tab's URL (via activeTab permission),
// shows it, and on button-click asks the background service worker to
// POST it to /api/v1/employers/connect.
//
// Rails:
//   * ZERO DOM reads on the active tab (activeTab grants URL + title,
//     nothing else).
//   * Client-side https + prohibited-host guard as a UX shortcut. The
//     server enforces the same rails independently.
//   * Every message to the SW is a JSON object with a discriminator.
import { STORAGE_KEY_API_BASE } from "../lib/constants.js";
import { isProhibitedHost, isHttpsUrl, hostOf } from "../lib/url.js";

const el = (id) => document.getElementById(id);

async function _init() {
  // Restore saved API base.
  const r = await chrome.storage.local.get([STORAGE_KEY_API_BASE]);
  const saved = r[STORAGE_KEY_API_BASE] || "";
  el("api-base").value = saved;
  el("api-base").addEventListener("change", async (e) => {
    await chrome.storage.local.set({ [STORAGE_KEY_API_BASE]: e.target.value.trim() });
  });

  // Read the active tab URL.
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const rawUrl = tab && tab.url ? tab.url : "";
  el("tab-url").textContent = rawUrl || "(no active tab URL)";

  const status = el("status");
  const btn = el("capture-btn");

  if (!rawUrl) {
    status.style.display = "block";
    status.className = "status err";
    status.textContent = "No active tab URL — is this a chrome:// or extensions page?";
    return;
  }
  if (!isHttpsUrl(rawUrl)) {
    status.style.display = "block";
    status.className = "status err";
    status.textContent = "Only https:// URLs can be captured. This is a Fynd rail.";
    return;
  }
  if (isProhibitedHost(rawUrl)) {
    status.style.display = "block";
    status.className = "status warn";
    status.textContent = `Blocked host: ${hostOf(rawUrl)}. LinkedIn / Indeed / Handshake are refused at capture — their terms don't permit third-party ingestion.`;
    return;
  }

  btn.disabled = false;
  btn.addEventListener("click", async () => {
    const apiBase = el("api-base").value.trim();
    if (!apiBase) {
      status.style.display = "block";
      status.className = "status err";
      status.textContent = "Set your Fynd API base URL above first.";
      return;
    }
    btn.disabled = true;
    status.style.display = "block";
    status.className = "status";
    status.textContent = "Submitting…";
    try {
      const resp = await chrome.runtime.sendMessage({
        type: "POST_CAPTURE",
        apiBase,
        rawUrl,
      });
      if (resp && resp.ok) {
        status.className = "status ok";
        const verdict = resp.body && resp.body.verdict ? resp.body.verdict : "queued";
        status.textContent = `Server ${resp.status}: ${verdict}. Check your Employers Queue in Fynd.`;
      } else if (resp && resp.verdict === "client_reject") {
        status.className = "status warn";
        status.textContent = `Client-side reject: ${resp.reason}` + (
          resp.recent_count ? ` (${resp.recent_count}/${resp.cap} this hour)` : ""
        );
      } else if (resp && resp.verdict === "server") {
        status.className = "status err";
        status.textContent = `Server ${resp.status}: ${
          (resp.body && resp.body.detail) || (resp.body && resp.body.reason) || "rejected"
        }`;
      } else {
        status.className = "status err";
        status.textContent = `Error: ${resp && resp.detail ? resp.detail : "unknown"}`;
      }
    } finally {
      btn.disabled = false;
    }
  });
}

_init();
