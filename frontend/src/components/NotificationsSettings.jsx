import React, { useEffect, useState, useCallback } from 'react';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import { Bell, BellOff, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import {
  isPushSupported, permissionState, fetchPreferences, updatePreferences,
  fetchVapidPublicKey, subscribe, unsubscribe, sendTest,
} from '../lib/push';

const CATEGORY_LABELS = {
  application_updates: 'Application updates',
  interviews:          'Interviews scheduled',
  approvals_expiring:  'Approval expiring reminders',
  receipts:            'New submission receipts',
  support:             'Support ticket replies',
};

const CATEGORY_HINTS = {
  application_updates: 'When an outcome (response / rejection / offer) is logged for one of your applications.',
  interviews:          'When an interview is scheduled or rescheduled on your tracker.',
  approvals_expiring:  'When an authorized submission window has less than 12 hours remaining.',
  receipts:            'When a submission receipt is written for one of your applications.',
  support:             'When a support member replies to one of your tickets.',
}

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
        <div className="flex items-center gap-2 muted text-sm py-6"><Loader2 className="h-4 w-4 animate-spin"/> Loading notification settings…</div>
      ) : (
        <>
          {supported && configReady && (
            <div className="flex items-center justify-between py-3 border-b border-line dark:border-line-dark">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Bell className="h-4 w-4"/>
                  <span className="text-sm font-medium">Push notifications on this device</span>
                  <span
                    data-testid="notifications-device-state"
                    className={`pill ${hasActiveSubscription ? 'pill-accent' : 'pill-neutral'}`}
                  >
                    {hasActiveSubscription ? 'active' : 'inactive'}
                  </span>
                </div>
                <p className="text-xs muted mt-1">
                  Enable on each device you want to receive push on. Permission is asked only when you click Enable.
                </p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {hasActiveSubscription ? (
                  <>
                    <Button
                      data-testid="notifications-test-btn"
                      variant="secondary" size="sm" onClick={handleTest} loading={busy}
                    >Send test</Button>
                    <Button
                      data-testid="notifications-disable-btn"
                      variant="secondary" size="sm" onClick={handleDisable} loading={busy}
                    ><BellOff className="h-3 w-3 mr-1"/>Disable</Button>
                  </>
                ) : (
                  <Button
                    data-testid="notifications-enable-btn"
                    variant="accent" size="sm" onClick={handleEnable} loading={busy}
                    disabled={permission === 'denied'}
                  ><Bell className="h-3 w-3 mr-1"/>Enable</Button>
                )}
              </div>
            </div>
          )}

          <div data-testid="notifications-categories" className="pt-3">
            <p className="text-xs muted mb-2">
              Even if this device is active, categories you turn off will never dispatch.
            </p>
            {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
              <div key={key} className="flex items-start justify-between gap-4 py-3 border-b border-line dark:border-line-dark last:border-b-0">
                <div className="min-w-0">
                  <div className="text-sm font-medium">{label}</div>
                  <p className="text-xs muted mt-1">{CATEGORY_HINTS[key] || catalog[key] || ''}</p>
                </div>
                <label className="inline-flex items-center gap-2 select-none flex-shrink-0">
                  <input
                    type="checkbox"
                    data-testid={`notifications-cat-${key}`}
                    checked={!!(prefs && prefs[key])}
                    onChange={(e) => handleToggleCategory(key, e.target.checked)}
                    className="h-4 w-4"
                  />
                  <span className="text-xs muted">{(prefs && prefs[key]) ? 'on' : 'off'}</span>
                </label>
              </div>
            ))}
          </div>

          {status && (
            <div data-testid="notifications-status-message" className="mt-4 text-xs text-accent flex items-center gap-1">
              <CheckCircle2 className="h-3.5 w-3.5"/> {status}
            </div>
          )}
          {error && (
            <div data-testid="notifications-error-message" className="mt-4 text-xs text-red-600 dark:text-red-400">
              {error}
            </div>
          )}
          {testResult && (
            <div className="mt-2 text-[11px] muted" data-testid="notifications-test-summary">
              Test dispatch: sent {testResult.sent}, failed {testResult.failed}, skipped {testResult.skipped}, pruned {testResult.pruned}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
