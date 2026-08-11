import React, { useEffect, useState, useCallback } from 'react';
import Card, { CardHeader } from '../components/ui/Card';
import { AlertTriangle, Loader2 } from 'lucide-react';
import {
  isPushSupported, permissionState, fetchPreferences, updatePreferences,
  fetchVapidPublicKey, subscribe, unsubscribe, sendTest,
} from '../lib/push';
import { PushDeviceBar } from './notifications/PushDeviceBar';
import { CategoryTogglesList } from './notifications/CategoryTogglesList';
import { NotificationsStatusMessages } from './notifications/NotificationsStatusMessages';

/**
 * Notifications settings — VAPID push + per-category preferences.
 *
 * 2026-08-11 — P2 Tier-2 split: sub-components live under
 * `./notifications/`. This file owns state, async actions, and the
 * top-level Card/header/loader. Zero behaviour change; all testids
 * preserved.
 */
export default function NotificationsSettings() {
  const [permission, setPermission] = useState(permissionState());
  const [supported] = useState(isPushSupported());
  const [vapid, setVapid] = useState(null);
  const [prefs, setPrefs] = useState(null);
  const [catalog, setCatalog] = useState({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [testResult, setTestResult] = useState(null);
  const [hasActiveSubscription, setHasActiveSubscription] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [v, p] = await Promise.all([fetchVapidPublicKey(), fetchPreferences()]);
      setVapid(v);
      setPrefs(p.categories);
      setCatalog(p.catalog || {});
      if (supported && v && v.ok) {
        const reg = await navigator.serviceWorker.getRegistration('/sw.js');
        if (reg) {
          const sub = await reg.pushManager.getSubscription();
          setHasActiveSubscription(!!sub);
        } else {
          setHasActiveSubscription(false);
        }
      }
      setPermission(permissionState());
    } catch (e) {
      setError('Could not load notification settings.');
    } finally {
      setLoading(false);
    }
  }, [supported]);

  useEffect(() => { refresh(); }, [refresh]);

  async function handleEnable() {
    setBusy(true); setError(''); setStatus('');
    try {
      await subscribe();
      setStatus('Notifications enabled on this device.');
      setPermission(permissionState());
      setHasActiveSubscription(true);
    } catch (e) {
      const msg = e && e.message ? e.message : 'subscribe_failed';
      const friendly = {
        push_unsupported: 'This browser does not support push notifications.',
        permission_denied: 'Notification permission was not granted.',
        vapid_not_configured: 'Push is not configured on this server yet.',
      }[msg] || 'Could not enable push notifications.';
      setError(friendly);
      setPermission(permissionState());
    } finally {
      setBusy(false);
    }
  }

  async function handleDisable() {
    setBusy(true); setError(''); setStatus('');
    try {
      await unsubscribe();
      setStatus('Push notifications disabled on this device.');
      setHasActiveSubscription(false);
    } catch (e) {
      setError('Could not disable notifications.');
    } finally {
      setBusy(false);
    }
  }

  async function handleToggleCategory(key, next) {
    setError(''); setStatus('');
    try {
      const patch = { [key]: next };
      const res = await updatePreferences(patch);
      setPrefs(res.categories);
    } catch (e) {
      setError('Could not update preference.');
    }
  }

  async function handleTest() {
    setBusy(true); setError(''); setStatus(''); setTestResult(null);
    try {
      const summary = await sendTest();
      setTestResult(summary);
      if (summary.reason === 'no_active_subscriptions') {
        setStatus('Test skipped — no active subscription on any device.');
      } else if (summary.reason === 'opted_out') {
        setStatus('Test skipped — the "Application updates" category is off.');
      } else if (summary.sent > 0) {
        setStatus(`Sent ${summary.sent} test notification${summary.sent === 1 ? '' : 's'}.`);
      } else if (summary.reason === 'vapid_not_configured') {
        setError('Push is not configured on this server.');
      } else {
        setStatus('Test dispatched.');
      }
    } catch (e) {
      if (e && e.response && e.response.status === 429) {
        setError('Rate limited — please wait a bit before sending another test.');
      } else {
        setError('Could not send test notification.');
      }
    } finally {
      setBusy(false);
    }
  }

  const configReady = vapid && vapid.ok;

  return (
    <Card>
      <CardHeader
        title="Notifications"
        subtitle="Standards-based web push (VAPID) — details load in-app; push payloads never carry employer / salary / sealed content."
        action={
          <span data-testid="notifications-permission-status" className="text-xs muted">
            Permission: <strong>{permission}</strong>{!supported ? ' · unsupported browser' : ''}
          </span>
        }
      />

      {!supported && (
        <div data-testid="notifications-unsupported" className="rounded-md border border-line dark:border-line-dark bg-line/5 text-sm px-3 py-2 mb-4">
          Push notifications are not supported in this browser. The rest of the product still works.
        </div>
      )}
      {supported && !configReady && !loading && (
        <div data-testid="notifications-not-configured" className="rounded-md border border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-300 text-sm px-3 py-2 mb-4 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5" />
          <span>Web push is not yet configured on this server. Notifications can't be enabled right now.</span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 muted text-sm py-6">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading notification settings…
        </div>
      ) : (
        <>
          {supported && configReady && (
            <PushDeviceBar
              hasActiveSubscription={hasActiveSubscription}
              permission={permission}
              busy={busy}
              onEnable={handleEnable}
              onDisable={handleDisable}
              onTest={handleTest}
            />
          )}

          <CategoryTogglesList
            prefs={prefs}
            catalog={catalog}
            onToggle={handleToggleCategory}
          />

          <NotificationsStatusMessages status={status} error={error} testResult={testResult} />
        </>
      )}
    </Card>
  );
}
