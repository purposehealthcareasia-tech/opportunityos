import axios from 'axios';

const BASE = process.env.REACT_APP_BACKEND_URL;

export const api = axios.create({
  baseURL: BASE,
  timeout: 20000,
});

let _token = null;
export function setAuthToken(token) {
  _token = token;
  if (token) {
    localStorage.setItem('oppos.token', token);
    api.defaults.headers.common.Authorization = `Bearer ${token}`;
  } else {
    localStorage.removeItem('oppos.token');
    delete api.defaults.headers.common.Authorization;
  }
}

export function loadAuthToken() {
  const t = localStorage.getItem('oppos.token');
  if (t) {
    _token = t;
    api.defaults.headers.common.Authorization = `Bearer ${t}`;
  }
  return t;
}

export function getToken() {
  return _token || localStorage.getItem('oppos.token');
}

export function newIdempotencyKey() {
  // Prefer crypto.randomUUID when available (all modern browsers).
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'oppos-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function withIdempotency(config = {}) {
  const headers = { ...(config.headers || {}), 'Idempotency-Key': newIdempotencyKey() };
  return { ...config, headers };
}

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      setAuthToken(null);
    }
    return Promise.reject(err);
  }
);
