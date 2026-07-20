import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, Clock, AlertTriangle, ShieldCheck, Loader2 } from 'lucide-react';
import { api } from '../lib/api';

/**
 * S13 — Approvals queue.
 *
 * Rules:
 *  - Only awaiting_approval applications appear here (approvable state).
 *  - Batch select + approve (best-effort per row; failures shown inline).
 *  - Post-approve, each row shows a 72h expiry countdown.
 *  - Daily-cap meter shown at the top ("n/15 today", pulled from /subscriptions/me
 *    + /applications/receipts/mine filtered to today).
 */

function hoursMinutesRemaining(expiresAt) {
  if (!expiresAt) return null;
  const exp = new Date(expiresAt).getTime();
  if (Number.isNaN(exp)) return null;
  const diff = Math.max(0, exp - Date.now());
  const hrs = Math.floor(diff / (60 * 60 * 1000));
  const mins = Math.floor((diff % (60 * 60 * 1000)) / (60 * 1000));
  return { hrs, mins, total: diff };
}

function submittedToday(receipts) {
  if (!receipts) return 0;
  const today = new Date();
  today.setUTCHours(0, 0, 0, 0);
  return receipts.filter((r) => new Date(r.ts).getTime() >= today.getTime()).length;
}

export default function ApprovalsPage() {
  const [state, setState] = useState({ apps: [], approved: [], loading: true, error: null });
  const [sub, setSub] = useState(null);
  const [receipts, setReceipts] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState(null);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const [appsRes, subRes, recRes] = await Promise.all([
        api.get('/api/v1/applications'),
        api.get('/api/v1/subscriptions/me'),
        api.get('/api/v1/applications/receipts/mine'),
      ]);
      const apps = (appsRes.data.applications || []);
      setState({
        apps: apps.filter((a) => a.state === 'awaiting_approval'),
        approved: apps.filter((a) => a.state === 'approved'),
        loading: false,
        error: null,
      });
      setSub(subRes.data);
      setReceipts(recRes.data.receipts || []);
    } catch (e) {
      setState({ apps: [], approved: [], loading: false, error: e?.response?.data?.detail || 'Failed to load approvals' });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = (id) => {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const allSelected = state.apps.length > 0 && state.apps.every((a) => selected.has(a.id));
  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(state.apps.map((a) => a.id)));
  };

  const approveOne = useCallback(async (appId) => {
    try {
      await api.post(`/api/v1/applications/${appId}/approve`, {});
      setFlash({ kind: 'ok', message: 'Approved. 72h authorization window is live.' });
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setFlash({ kind: 'warn', message: (detail?.message || detail?.error || 'Could not approve — try again.') });
    }
    await load();
  }, [load]);

  const approveBatch = useCallback(async () => {
    if (selected.size === 0) return;
    setBusy(true);
    try {
      const res = await api.post('/api/v1/applications/approve-batch', {
        application_ids: [...selected],
      });
      const s = res.data.summary || {};
      setFlash({ kind: s.failed ? 'warn' : 'ok', message: `${s.approved || 0} approved · ${s.failed || 0} failed.` });
      setSelected(new Set());
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail?.error || 'Batch approve failed.' });
    } finally {
      setBusy(false);
    }
  }, [selected, load]);

  const revokeOne = useCallback(async (appId) => {
    try {
      await api.post(`/api/v1/applications/${appId}/revoke-authorization`, {});
      setFlash({ kind: 'ok', message: 'Authorization revoked. Packet moved back to awaiting-approval.' });
    } catch (e) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail?.error || 'Could not revoke.' });
    }
    await load();
  }, [load]);

  const usedToday = useMemo(() => submittedToday(receipts), [receipts]);
  const cap = sub?.daily_submit_cap ?? 3;

  return (
    <div className="space-y-8" data-testid="approvals-page">
      <header className="space-y-1">
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">Approvals</h1>
        <p className="muted max-w-3xl">
          Applications that are ready but need your final go-ahead. Approving creates a 72-hour
          authorization scope for that specific packet — if the resume or a screener answer changes,
          you'll need to re-approve before you can submit.
        </p>
      </header>

      {flash && (
        <div
          data-testid="approvals-flash"
          className={`rounded-md border px-3 py-2 text-sm ${flash.kind === 'ok' ? 'bg-accent/10 border-accent/40 text-accent' : 'bg-amber-50 border-amber-400 text-amber-900 dark:bg-amber-950 dark:text-amber-200'}`}
        >
          {flash.message}
        </div>
      )}

      <section className="rounded-md border border-line dark:border-line-dark p-4 bg-neutral-50 dark:bg-neutral-900/40">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm muted">Daily submit cap</div>
            <div className="text-2xl font-semibold" data-testid="daily-cap-meter">
              {usedToday}/{cap} today
            </div>
            <div className="text-xs muted mt-1">
              {sub ? `Plan: ${sub.label}. Resets at UTC midnight.` : 'Loading plan…'}
            </div>
          </div>
          <div className="h-16 w-2 rounded-full bg-neutral-200 dark:bg-neutral-800 relative overflow-hidden">
            <div
              className="absolute bottom-0 left-0 right-0 bg-accent"
              style={{ height: `${Math.min(100, (usedToday / Math.max(cap, 1)) * 100)}%` }}
            />
          </div>
        </div>
      </section>

      {state.loading ? (
        <div className="flex items-center gap-2 muted"><Loader2 className="h-4 w-4 animate-spin" /> Loading approvals…</div>
      ) : state.error ? (
        <div className="rounded-md border border-red-400 bg-red-50 dark:bg-red-950 dark:text-red-200 text-red-800 px-3 py-2 text-sm">
          {state.error}
        </div>
      ) : state.apps.length === 0 && state.approved.length === 0 ? (
        <div className="rounded-md border border-line dark:border-line-dark p-6 muted" data-testid="approvals-empty">
          Nothing awaiting approval. Prepare a shortlisted job on the Feed, then come back to sign off.
        </div>
      ) : (
        <>
          {state.apps.length > 0 && (
            <section className="space-y-3" data-testid="approvals-queue">
              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    data-testid="approvals-select-all"
                  />
                  Select all ({state.apps.length})
                </label>
                <button
                  type="button"
                  className="btn-primary disabled:opacity-50"
                  disabled={selected.size === 0 || busy}
                  onClick={approveBatch}
                  data-testid="approvals-batch-approve-btn"
                >
                  {busy ? 'Approving…' : `Approve selected (${selected.size})`}
                </button>
              </div>
              <ul className="space-y-2">
                {state.apps.map((a) => (
                  <ApprovalRow
                    key={a.id}
                    app={a}
                    selected={selected.has(a.id)}
                    onToggle={() => toggle(a.id)}
                    onApprove={() => approveOne(a.id)}
                  />
                ))}
              </ul>
            </section>
          )}
          {state.approved.length > 0 && (
            <section className="space-y-3" data-testid="approvals-approved-list">
              <h2 className="text-lg font-semibold">Approved — awaiting submit</h2>
              <ul className="space-y-2">
                {state.approved.map((a) => (
                  <ApprovedRow key={a.id} app={a} onRevoke={() => revokeOne(a.id)} />
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function ApprovalRow({ app, selected, onToggle, onApprove }) {
  const snap = app.job_snapshot || {};
  return (
    <li className="rounded-md border border-line dark:border-line-dark p-3 flex items-center gap-3" data-testid={`approvals-row-${app.id}`}>
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        data-testid={`approvals-select-${app.id}`}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">{snap.title || 'Untitled role'}</span>
          {snap.is_sample && <span className="pill pill-neutral text-xs">SAMPLE</span>}
        </div>
        <div className="text-xs muted truncate">{snap.company_name || 'Unknown company'} · {snap.location || 'Location N/A'}</div>
      </div>
      <Link to={`/applications/${app.id}/prep`} className="pill pill-neutral text-xs no-underline" data-testid={`approvals-open-prep-${app.id}`}>
        Open packet
      </Link>
      <button
        type="button"
        className="btn-primary text-sm"
        onClick={onApprove}
        data-testid={`approvals-approve-${app.id}`}
      >
        Approve
      </button>
    </li>
  );
}

function ApprovedRow({ app, onRevoke }) {
  const snap = app.job_snapshot || {};
  const rem = hoursMinutesRemaining(app.authorization_expires_at);
  return (
    <li className="rounded-md border border-accent/40 bg-accent/5 p-3 flex items-center gap-3" data-testid={`approvals-approved-row-${app.id}`}>
      <ShieldCheck className="h-5 w-5 text-accent" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">{snap.title || 'Untitled role'}</span>
          {snap.is_sample && <span className="pill pill-neutral text-xs">SAMPLE</span>}
        </div>
        <div className="text-xs muted flex items-center gap-2 mt-0.5">
          <Clock className="h-3 w-3" />
          {rem === null
            ? 'expiry unknown'
            : rem.total === 0
              ? <span className="text-red-500 font-medium">expired — re-approve</span>
              : <span data-testid={`approvals-expiry-${app.id}`}>expires in {rem.hrs}h {rem.mins}m</span>}
        </div>
      </div>
      <Link to={`/applications/${app.id}/prep`} className="pill pill-neutral text-xs no-underline">
        Open packet
      </Link>
      <button
        type="button"
        className="text-xs muted hover:text-red-500"
        onClick={onRevoke}
        data-testid={`approvals-revoke-${app.id}`}
      >
        Revoke
      </button>
    </li>
  );
}
