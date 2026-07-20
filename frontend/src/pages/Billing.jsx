import React, { useCallback, useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { CreditCard, Check, AlertTriangle, Loader2, RefreshCw, Info } from 'lucide-react';
import { api } from '../lib/api';

/**
 * S19 — Billing.
 * - Current plan card + usage meters showing the three VERBATIM definitions.
 * - Upgrade/downgrade via Stripe test checkout (hosted).
 * - ≤2-click cancel + 7-day self-serve refund note + auto-refund action.
 * - FOUNDER19 coupon input.
 */

export default function BillingPage() {
  const [state, setState] = useState({ loading: true, error: null, catalog: null, usage: null, sub: null, invoices: [] });
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState(null);
  const [coupon, setCoupon] = useState('');
  const [couponVerdict, setCouponVerdict] = useState(null);
  const location = useLocation();

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const [cat, usage, sub, inv] = await Promise.all([
        api.get('/api/v1/billing/catalog'),
        api.get('/api/v1/usage/me'),
        api.get('/api/v1/subscriptions/me'),
        api.get('/api/v1/billing/invoices'),
      ]);
      setState({ loading: false, error: null,
                 catalog: cat.data, usage: usage.data, sub: sub.data,
                 invoices: inv.data.invoices || [] });
    } catch (e) {
      setState({ loading: false, error: 'Failed to load billing', catalog: null, usage: null, sub: null, invoices: [] });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Return path from Stripe: ?session_id=cs_test_... → sync
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const sid = params.get('session_id');
    if (!sid) return;
    (async () => {
      try {
        const r = await api.post('/api/v1/billing/session-confirm', { session_id: sid });
        if (r.data.payment_status === 'paid') {
          setFlash({ kind: 'ok', message: `Payment complete. You're now on ${r.data.plan_after.toUpperCase()}.` });
        } else {
          setFlash({ kind: 'warn', message: `Payment status: ${r.data.payment_status}` });
        }
        await load();
      } catch (e) {
        setFlash({ kind: 'warn', message: 'Could not sync session.' });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search]);

  const validateCoupon = async () => {
    if (!coupon.trim()) { setCouponVerdict(null); return; }
    try {
      const r = await api.post('/api/v1/billing/coupon/apply', { code: coupon.trim() });
      setCouponVerdict(r.data);
    } catch (e) {
      setCouponVerdict({ valid: false, message: 'Could not validate.' });
    }
  };

  const startCheckout = async (lookup_key) => {
    setBusy(true);
    try {
      const origin_url = window.location.origin;
      const body = { lookup_key, origin_url };
      if (coupon.trim() && couponVerdict?.valid) body.coupon = coupon.trim();
      const r = await api.post('/api/v1/billing/checkout', body);
      window.location.assign(r.data.checkout_url);
    } catch (e) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail?.message || 'Checkout failed.' });
      setBusy(false);
    }
  };

  const cancel = async () => {
    setBusy(true);
    try {
      const r = await api.post('/api/v1/billing/cancel', {});
      setFlash({ kind: 'ok', message: r.data.message });
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail?.message || 'Cancel failed.' });
    } finally { setBusy(false); }
  };

  const refund = async () => {
    setBusy(true);
    try {
      const r = await api.post('/api/v1/billing/refund', {});
      setFlash({ kind: 'ok', message: `Refunded $${r.data.amount}. You're back on Free.` });
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail?.message || 'Refund failed.' });
    } finally { setBusy(false); }
  };

  if (state.loading) return <div className="flex items-center gap-2 muted"><Loader2 className="h-4 w-4 animate-spin" /> Loading billing…</div>;
  if (state.error) return <div className="rounded-md border border-red-400 bg-red-50 dark:bg-red-950 px-3 py-2 text-sm">{state.error}</div>;

  const u = state.usage; const sub = state.sub; const cat = state.catalog;
  const planLabel = sub?.label || sub?.plan;
  const paidPlan = sub?.plan && sub.plan !== 'free';

  return (
    <div className="space-y-8" data-testid="billing-page">
      <header className="space-y-1">
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight flex items-center gap-2"><CreditCard className="h-6 w-6" /> Billing</h1>
        <p className="muted max-w-3xl">Stripe test-mode. No real charges. FOUNDER19 unlocks the Plus plan at $19/mo forever.</p>
      </header>

      {flash && (
        <div className={`rounded-md border px-3 py-2 text-sm ${flash.kind === 'ok' ? 'bg-accent/10 border-accent/40 text-accent' : 'bg-amber-50 border-amber-400 text-amber-900 dark:bg-amber-950 dark:text-amber-200'}`} data-testid="billing-flash">
          {flash.message}
        </div>
      )}

      <section className="rounded-md border border-line dark:border-line-dark p-4 flex items-center justify-between" data-testid="current-plan-card">
        <div>
          <div className="text-xs uppercase tracking-wide muted">Current plan</div>
          <div className="text-2xl font-semibold" data-testid="current-plan-name">{planLabel}</div>
          {sub?.cancel_at_period_end && (
            <div className="text-xs text-amber-600 dark:text-amber-400 mt-1">
              Cancellation scheduled — features remain until period end.
            </div>
          )}
        </div>
        {paidPlan && !sub?.cancel_at_period_end && (
          <button
            type="button"
            className="text-sm underline text-red-600 dark:text-red-400"
            onClick={cancel}
            disabled={busy}
            data-testid="cancel-btn"
          >
            Cancel plan
          </button>
        )}
      </section>

      <section className="space-y-3" data-testid="usage-meters">
        <h2 className="text-lg font-semibold">Usage meters</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <MeterCard title="jobs_processed" testid="meter-jobs" definition={u.meter_definitions_verbatim.jobs_processed} data={u.jobs_processed} />
          <MeterCard title="applications_prepared" testid="meter-prepared" definition={u.meter_definitions_verbatim.applications_prepared} data={u.applications_prepared} />
          <MeterCard title="apps_submitted" testid="meter-submitted" definition={u.meter_definitions_verbatim.apps_submitted} data={u.apps_submitted} />
        </div>
      </section>

      <section className="space-y-3" data-testid="plan-catalog">
        <h2 className="text-lg font-semibold">Change plan</h2>
        <div className="rounded-md border border-line dark:border-line-dark p-3 space-y-2 max-w-md">
          <label className="text-sm block">Coupon code</label>
          <div className="flex items-center gap-2">
            <input
              type="text"
              className="flex-1 rounded-md border border-line dark:border-line-dark bg-transparent p-2 text-sm"
              placeholder="e.g. FOUNDER19"
              value={coupon}
              onChange={(e) => setCoupon(e.target.value)}
              onBlur={validateCoupon}
              data-testid="coupon-input"
            />
            <button type="button" className="pill pill-neutral text-xs" onClick={validateCoupon}>Apply</button>
          </div>
          {couponVerdict && (
            <div className={`text-xs ${couponVerdict.valid ? 'text-accent' : 'muted'}`} data-testid="coupon-verdict">
              {couponVerdict.message}
            </div>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {Object.entries(cat.plans).map(([key, plan]) => (
            <div key={key} className="rounded-md border border-line dark:border-line-dark p-3" data-testid={`plan-card-${plan.plan}`}>
              <div className="text-xs uppercase tracking-wide muted">{plan.label}</div>
              <div className="text-2xl font-semibold">${plan.amount}/mo</div>
              <ul className="text-xs muted list-disc pl-4 mt-2 space-y-0.5">
                <li>{cat.caps_by_plan[plan.plan].jobs_hourly}/hr jobs_processed</li>
                <li>{cat.caps_by_plan[plan.plan].prepared_monthly}/mo applications_prepared{plan.plan==='max' ? ' (soft)' : ''}</li>
                <li>{cat.caps_by_plan[plan.plan].submits_daily}/day apps_submitted</li>
              </ul>
              <button
                type="button"
                className="btn-primary text-sm mt-3 w-full"
                disabled={busy || sub?.plan === plan.plan}
                onClick={() => startCheckout(key)}
                data-testid={`checkout-btn-${plan.plan}`}
              >
                {sub?.plan === plan.plan ? 'Current plan' : `Choose ${plan.label}`}
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3" data-testid="refund-section">
        <h2 className="text-lg font-semibold">Refund</h2>
        <div className="rounded-md border border-line dark:border-line-dark p-3 text-sm">
          <div className="flex items-start gap-2">
            <Info className="h-4 w-4 mt-0.5 muted" />
            <div>
              First purchase, within 7 days, one click. This walks you back to Free and refunds the most recent invoice.
              <div className="mt-2">
                <button type="button" className="text-xs pill pill-neutral" onClick={refund} data-testid="refund-btn">
                  <RefreshCw className="h-3 w-3 inline mr-1" /> Auto-refund most recent
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {state.invoices.length > 0 && (
        <section className="space-y-2" data-testid="invoice-list">
          <h2 className="text-lg font-semibold">Invoices</h2>
          <ul className="space-y-1 text-sm">
            {state.invoices.map((i) => (
              <li key={i.id} className="rounded-md border border-line dark:border-line-dark p-2 flex items-center gap-3 text-xs">
                <span className="font-mono flex-1 truncate">{i.session_id}</span>
                <span className="muted">${i.amount} {i.currency?.toUpperCase()}</span>
                <span className={`pill text-[10px] ${i.payment_status === 'paid' ? 'pill-accent' : 'pill-neutral'}`}>{i.payment_status}</span>
                <span className="muted">{new Date(i.created_at).toLocaleDateString()}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function MeterCard({ title, testid, definition, data }) {
  const pct = Math.min(100, Math.round((data.used / Math.max(data.cap, 1)) * 100));
  const hardHit = !data.soft && data.used >= data.cap;
  const softHit = data.soft && data.used >= data.cap;
  return (
    <div className="rounded-md border border-line dark:border-line-dark p-3 space-y-2" data-testid={testid}>
      <div className="text-xs uppercase tracking-wide muted flex items-center gap-1">
        {title}
        {data.soft && <span className="pill pill-neutral text-[10px]">soft</span>}
      </div>
      <div className="text-2xl font-semibold">
        {data.used} <span className="text-sm muted font-normal">/ {data.cap}</span>
      </div>
      <div className="h-1.5 rounded-full bg-neutral-200 dark:bg-neutral-800 overflow-hidden">
        <div className={`h-full ${hardHit ? 'bg-red-500' : softHit ? 'bg-amber-400' : 'bg-accent'}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-[11px] muted italic" data-testid={`${testid}-definition`}>
        {title} = {definition}
      </p>
      <p className="text-[10px] muted">Resets {new Date(data.resets_at).toLocaleString()}</p>
      {hardHit && (
        <div className="text-xs text-red-500 flex items-center gap-1" data-testid={`${testid}-cap-hit`}>
          <AlertTriangle className="h-3 w-3" /> Cap hit — upgrade or wait for reset
        </div>
      )}
      {softHit && (
        <div className="text-xs text-amber-500 flex items-center gap-1"><AlertTriangle className="h-3 w-3" /> Soft cap reached</div>
      )}
    </div>
  );
}
