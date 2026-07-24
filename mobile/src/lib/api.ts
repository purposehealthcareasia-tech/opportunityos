import axios from 'axios';
import { Platform } from 'react-native';

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

export const api = axios.create({
  baseURL: BASE,
  timeout: 20000,
  withCredentials: true,
});

export function newIdempotencyKey(): string {
  return 'oppos-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function withIdempotency(config: any = {}) {
  const headers = { ...(config.headers || {}), 'Idempotency-Key': newIdempotencyKey() };
  return { ...config, headers };
}

let onUnauthorized: (() => void) | null = null;
export function setOnUnauthorized(fn: () => void) {
  onUnauthorized = fn;
}

// CSRF token interceptor (reads from cookie set by backend)
api.interceptors.request.use((cfg) => {
  if (Platform.OS === 'web' && typeof document !== 'undefined') {
    const match = document.cookie.match(/(?:^|; )oppos_csrf=([^;]*)/);
    if (match) {
      cfg.headers['X-CSRF-Token'] = decodeURIComponent(match[1]);
    }
  }
  return cfg;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && typeof onUnauthorized === 'function') {
      onUnauthorized();
    }
    return Promise.reject(err);
  },
);
