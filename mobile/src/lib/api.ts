import axios from 'axios';
import { Platform } from 'react-native';
import { getTokens } from './session';

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

export const api = axios.create({
  baseURL: BASE,
  timeout: 20000,
  // withCredentials is needed on web for the browser cookie jar.
  // On native it has no effect (RN doesn't implement a cookie jar).
  ...(Platform.OS === 'web' ? { withCredentials: true } : {}),
});

/* ── Helpers ──────────────────────────────────────────────────── */

export function newIdempotencyKey(): string {
  return 'oppos-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function withIdempotency(config: any = {}) {
  const headers = { ...(config.headers || {}), 'Idempotency-Key': newIdempotencyKey() };
  return { ...config, headers };
}

/* ── Global 401 hook ──────────────────────────────────────────── */

let onUnauthorized: (() => void) | null = null;
export function setOnUnauthorized(fn: () => void) {
  onUnauthorized = fn;
}

/* ── Request interceptor ──────────────────────────────────────── */

const MUTATING = ['post', 'put', 'patch', 'delete'];

api.interceptors.request.use((cfg) => {
  if (Platform.OS === 'web') {
    // Web: browser sends cookies automatically via withCredentials.
    // We only need to read the JS-readable CSRF cookie for the header.
    if (typeof document !== 'undefined') {
      const match = document.cookie.match(/(?:^|; )oppos_csrf=([^;]*)/);
      if (match) {
        cfg.headers['X-CSRF-Token'] = decodeURIComponent(match[1]);
      }
    }
  } else {
    // Native: manually attach Cookie header + CSRF header from secure store.
    const { session, csrf } = getTokens();
    if (session) {
      const cookieParts = [`oppos_session=${session}`];
      if (csrf) cookieParts.push(`oppos_csrf=${csrf}`);
      cfg.headers['Cookie'] = cookieParts.join('; ');
    }
    if (csrf && MUTATING.includes((cfg.method || '').toLowerCase())) {
      cfg.headers['X-CSRF-Token'] = csrf;
    }
  }
  return cfg;
});

/* ── Response interceptor ─────────────────────────────────────── */

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && typeof onUnauthorized === 'function') {
      onUnauthorized();
    }
    return Promise.reject(err);
  },
);
