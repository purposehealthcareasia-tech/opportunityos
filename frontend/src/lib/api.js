import axios from 'axios';

const BASE = process.env.REACT_APP_BACKEND_URL;

// Cookie-first: every request carries credentials so the browser attaches the
// httpOnly session cookie AND the JS-readable CSRF cookie.
export const api = axios.create({
  baseURL: BASE,
  timeout: 20000,
  withCredentials: true,
});

const CSRF_COOKIE_NAME = 'oppos_csrf';
const STATE_METHODS = new Set(['post', 'put', 'patch', 'delete']);

function readCsrfCookie() {
  if (typeof document === 'undefined') return '';
  const match = document.cookie.split('; ').find((c) => c.startsWith(`${CSRF_COOKIE_NAME}=`));
  return match ? decodeURIComponent(match.split('=')[1]) : '';
}

// Attach X-CSRF-Token on state-changing verbs (double-submit contract).
api.interceptors.request.use((config) => {
  const method = (config.method || 'get').toLowerCase();
  if (STATE_METHODS.has(method)) {
    const csrf = readCsrfCookie();
    if (csrf) {
      config.headers = { ...(config.headers || {}), 'X-CSRF-Token': csrf };
    }
  }
  return config;
});

export function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'oppos-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function withIdempotency(config = {}) {
  const headers = { ...(config.headers || {}), 'Idempotency-Key': newIdempotencyKey() };
  return { ...config, headers };
}

// Clear session on 401 so the router bounces to /login. No local token to nuke —
// the server-side session store is the sole source of truth.
let onUnauthorized = null;
export function setOnUnauthorized(fn) { onUnauthorized = fn; }

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && typeof onUnauthorized === 'function') {
      onUnauthorized();
    }
    return Promise.reject(err);
  },
);
