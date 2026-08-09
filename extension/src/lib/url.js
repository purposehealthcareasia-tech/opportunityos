// URL helpers. NO PAGE-CONTENT READS. Only reasons about the URL
// string of the active tab (surfaced via chrome.tabs.query).
//
// Mirrors backend/domains/supply/origin_resolver.py canonicalization
// (host lowercase, drop tracking params, strip fragment).
import { PROHIBITED_HOST_SUFFIXES } from "./constants.js";

const TRACKING_PARAMS = new Set([
  "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
  "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "source", "ref_src", "trk",
]);

export function normalizeUrl(raw) {
  const url = new URL(String(raw || "").trim());
  const kept = [];
  for (const [k, v] of url.searchParams.entries()) {
    if (TRACKING_PARAMS.has(k.toLowerCase())) continue;
    kept.push([k, v]);
  }
  const query = kept
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join("&");
  const host = (url.hostname || "").toLowerCase();
  return `${url.protocol}//${host}${url.pathname || "/"}${query ? "?" + query : ""}`;
}

export function hostOf(rawUrl) {
  try { return new URL(String(rawUrl || "")).hostname.toLowerCase(); }
  catch (_) { return ""; }
}

export function isProhibitedHost(rawUrl) {
  const host = hostOf(rawUrl);
  if (!host) return false;
  return PROHIBITED_HOST_SUFFIXES.some((s) => host === s || host.endsWith("." + s));
}

export function isHttpsUrl(rawUrl) {
  try { return new URL(String(rawUrl || "")).protocol === "https:"; }
  catch (_) { return false; }
}
