/* OpportunityOS Service Worker — Standards-based Web Push (VAPID).
 *
 * Handles push events + notification clicks. Payloads are always the
 * minimal shape the backend guarantees:
 *   { title, body, category, data: { application_id?, receipt_id?,
 *     interview_id?, outcome_id?, ticket_id?, url? } }
 *
 * The service worker never receives employer/salary/sealed/claim content;
 * the "url" field is always a relative in-app route (validated server-side).
 */
/* eslint-disable no-restricted-globals */

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  if (!event.data) return;
  let payload = { title: 'OpportunityOS', body: 'You have an update.' };
  try {
    payload = event.data.json();
  } catch (e) {
    try { payload.body = event.data.text() || payload.body; } catch (_) {}
  }
  const title = payload.title || 'OpportunityOS';
  const options = {
    body: payload.body || '',
    icon: '/logo192.png',
    badge: '/logo192.png',
    data: payload.data || {},
    tag: (payload.category || 'default') + ':' + ((payload.data && payload.data.dedup_key) || Date.now()),
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const data = event.notification.data || {};
  const url = (typeof data.url === 'string' && data.url.startsWith('/')) ? data.url : '/tracker';
  event.waitUntil((async () => {
    const allClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of allClients) {
      const clientUrl = new URL(client.url);
      if (clientUrl.pathname === url && 'focus' in client) {
        return client.focus();
      }
    }
    if (self.clients.openWindow) {
      return self.clients.openWindow(url);
    }
    return null;
  })());
});
