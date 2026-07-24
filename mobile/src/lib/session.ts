/**
 * Cross-platform session store.
 *
 * Web  → browser cookie jar (via withCredentials); this module is a no-op.
 * Native (iOS / Android) → expo-secure-store for oppos_session + oppos_csrf.
 *
 * The backend authenticates via Cookie header: the session token is HttpOnly
 * in the browser but we extract it from the Set-Cookie response header on
 * native (RN XMLHttpRequest exposes it, unlike browsers).
 */
import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

const SESSION_KEY = 'oppos_session';
const CSRF_KEY = 'oppos_csrf';

/* ── In-memory cache (mirrors secure-store on native) ──────────── */
let _session: string | null = null;
let _csrf: string | null = null;

/* ── Public API ─────────────────────────────────────────────────── */

/** Returns { session, csrf } from memory cache. */
export function getTokens(): { session: string | null; csrf: string | null } {
  return { session: _session, csrf: _csrf };
}

/** Persist tokens to secure storage (native) or no-op (web). */
export async function saveTokens(session: string, csrf: string): Promise<void> {
  _session = session;
  _csrf = csrf;
  if (Platform.OS !== 'web') {
    await Promise.all([
      SecureStore.setItemAsync(SESSION_KEY, session),
      SecureStore.setItemAsync(CSRF_KEY, csrf),
    ]);
  }
}

/** Clear tokens from memory + secure storage. */
export async function clearTokens(): Promise<void> {
  _session = null;
  _csrf = null;
  if (Platform.OS !== 'web') {
    await Promise.all([
      SecureStore.deleteItemAsync(SESSION_KEY),
      SecureStore.deleteItemAsync(CSRF_KEY),
    ]);
  }
}

/** Hydrate memory cache from secure-store on app boot (native only). */
export async function hydrateTokens(): Promise<boolean> {
  if (Platform.OS === 'web') return false; // browser handles cookies
  try {
    const [s, c] = await Promise.all([
      SecureStore.getItemAsync(SESSION_KEY),
      SecureStore.getItemAsync(CSRF_KEY),
    ]);
    if (s) {
      _session = s;
      _csrf = c;
      return true;
    }
  } catch {
    // SecureStore may throw on first access; treat as empty
  }
  return false;
}

/* ── Helpers for parsing Set-Cookie from response headers ──────── */

/**
 * Extract named cookie value from a raw Set-Cookie header string.
 * Only used on native where RN exposes Set-Cookie.
 */
function parseCookieValue(setCookieHeader: string, name: string): string | null {
  // set-cookie may be a single string or joined with ", " by some HTTP libs
  const parts = setCookieHeader.split(/,(?=\s*\w+=)/);
  for (const part of parts) {
    const trimmed = part.trim();
    const match = trimmed.match(new RegExp(`^${name}=([^;]+)`));
    if (match) return match[1];
  }
  return null;
}

/**
 * Given an axios response from login or signup, extract and persist session
 * cookies on native. No-op on web (browser handles Set-Cookie).
 */
export async function captureSessionFromResponse(response: any): Promise<void> {
  if (Platform.OS === 'web') return;
  const raw: string | undefined =
    response?.headers?.['set-cookie'] || response?.headers?.['Set-Cookie'];
  if (!raw) return;
  const session = parseCookieValue(raw, 'oppos_session');
  const csrf = parseCookieValue(raw, 'oppos_csrf');
  if (session && csrf) {
    await saveTokens(session, csrf);
  }
}
