/* Standards-based Web Push client helpers.
 *
 * Wires the browser Push API + Service Worker to the FastAPI backend.
 * Public API:
 *   - isPushSupported() → boolean
 *   - permissionState() → 'granted' | 'denied' | 'default' | 'unsupported'
 *   - fetchVapidPublicKey() → Promise<{ok, public_key, supported_categories}>
 *   - fetchPreferences() → Promise<{categories, catalog}>
 *   - updatePreferences(patch) → Promise<{categories}>
 *   - subscribe() → Promise<subscription-row-from-backend>
 *   - unsubscribe() → Promise<boolean>
 *   - sendTest() → Promise<summary>
 *
 * All state-changing calls go through the shared `api` axios instance
 * so cookies + CSRF header are attached automatically.
 */
import { api, withIdempotency } from './api';

const SW_URL = '/sw.js';

export function isPushSupported() {
  return typeof window !== 'undefined'
    && 'serviceWorker' in navigator
    && 'PushManager' in window
    && 'Notification' in window;
}

export function permissionState() {
  if (!isPushSupported()) return 'unsupported';
  return Notification.permission || 'default';
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const b64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = window.atob(b64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) arr[i] = raw.charCodeAt(i);
  return arr;
}

export async function fetchVapidPublicKey() {
  const res = await api.get('/api/v1/notifications/vapid-public-key');
  return res.data;
}

export async function fetchPreferences() {
  const res = await api.get('/api/v1/notifications/preferences');
  return res.data;
}

export async function updatePreferences(patch) {
  const res = await api.put('/api/v1/notifications/preferences', patch, withIdempotency());
  return res.data;
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) throw new Error('service_worker_unsupported');
  const existing = await navigator.serviceWorker.getRegistration(SW_URL);
  if (existing) return existing;
  return navigator.serviceWorker.register(SW_URL, { scope: '/' });
}

export async function subscribe() {
  if (!isPushSupported()) throw new Error('push_unsupported');

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') throw new Error('permission_denied');

  const vapid = await fetchVapidPublicKey();
  if (!vapid || !vapid.ok || !vapid.public_key) throw new Error('vapid_not_configured');

  const registration = await registerServiceWorker();
  await navigator.serviceWorker.ready;

  const existing = await registration.pushManager.getSubscription();
  const subscription = existing || await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(vapid.public_key),
  });

  const payload = subscription.toJSON();
  const res = await api.post('/api/v1/notifications/subscribe', {
    subscription: { endpoint: payload.endpoint, keys: payload.keys },
    user_agent: navigator.userAgent || null,
  }, withIdempotency());
  return res.data;
}

export async function unsubscribe() {
  if (!('serviceWorker' in navigator)) return false;
  const registration = await navigator.serviceWorker.getRegistration(SW_URL);
  if (!registration) return false;
  const sub = await registration.pushManager.getSubscription();
  if (!sub) return false;
  const endpoint = sub.endpoint;
  try {
    await sub.unsubscribe();
  } catch (_) {
    // Even if the browser-side unsubscribe fails, still tell the backend.
  }
  try {
    await api.post('/api/v1/notifications/unsubscribe', { endpoint }, withIdempotency());
    return true;
  } catch (_) {
    return false;
  }
}

export async function sendTest() {
  const res = await api.post('/api/v1/notifications/test', {}, withIdempotency());
  return res.data;
}
