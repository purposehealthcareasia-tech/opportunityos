import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Zap, Play, StopCircle, CheckCircle2, AlertTriangle, ShieldOff } from 'lucide-react';
import { api } from '../lib/api';

const FIXTURE_ALLOWLIST = [
  'fixture-ead@opportunityos.dev',
  'fixture-admin@opportunityos.dev',
];

// Phase 4 · Item 3 — Submit-Sprint UI (FIXTURE-ONLY).
// Renders a queue of shortlisted / approved FIXTURE applications with one-key
// confirm per slot. NEVER submits anything to a real employer.
export default function SubmitSprint() {
  const [me, setMe] = useState(null);
  const [apps, setApps] = useState([]);
  const [sprint, setSprint] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nav = useNavigate();

  const loadMe = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/auth/me');
      // /auth/me returns the user object directly (no wrapper).
      setMe(data || null);
    } catch { setMe(null); }
  }, []);

  const loadApps = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/applications?state=shortlisted');
      // Fixture-only: keep SampleCo / is_sample rows
      const fixture = (data.applications || data.rows || []).filter((a) => {
        const c = (a?.job_snapshot?.company_name || '').toLowerCase();
        return c.includes('sampleco') || a?.job_snapshot?.is_sample;
      });
      setApps(fixture);
    } catch (e) { setApps([]); }
  }, []);

  useEffect(() => { loadMe(); loadApps(); }, [loadMe, loadApps]);

  const start = async () => {
    setBusy(true); setError(null);
    try {
      const ids = apps.slice(0, 20).map((a) => a.id);
      const { data } = await api.post('/api/v1/sprint/start', { application_ids: ids });
      setSprint(data);
    } catch (e) {
      setError(e?.response?.data?.detail?.message || e?.response?.data?.detail?.error || 'Could not start sprint.');
    } finally { setBusy(false); }
  };

  const confirmSlot = useCallback(async (slot) => {
    if (!sprint || sprint.state !== 'running') return;
    setBusy(true); setError(null);
    try {
      const { data } = await api.post(`/api/v1/sprint/${sprint.id}/confirm`, {
        slot_id: slot.slot_id, confirm_token: slot.confirm_token,
      });
      setSprint(data.sprint);
    } catch (e) {
      setError(e?.response?.data?.detail?.error || 'Confirm failed.');
    } finally { setBusy(false); }
  }, [sprint]);

  const stop = async () => {
    if (!sprint) return;
    setBusy(true); setError(null);
    try {
      const { data } = await api.post(`/api/v1/sprint/${sprint.id}/stop`, {});
      setSprint(data);
    } catch (e) {
      setError(e?.response?.data?.detail?.error || 'Stop failed.');
    } finally { setBusy(false); }
  };

  // One-key confirm: press Enter on the FIRST queued slot
  useEffect(() => {
    const handler = (e) => {
      if (e.key !== 'Enter' || !sprint || sprint.state !== 'running') return;
      const next = (sprint.slots || []).find((s) => s.state === 'queued');
      if (next) confirmSlot(next);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [sprint, confirmSlot]);

  const isFixtureUser = !!(me && FIXTURE_ALLOWLIST.includes((me.email || '').toLowerCase()));

  if (!me) {
    return <div className="p-8"><p className="muted">Loading…</p></div>;
  }
  if (!isFixtureUser) {
    return (
      <div className="max-w-xl mx-auto py-16 px-6" data-testid="sprint-blocked">
        <div className="card p-6 text-center space-y-3">
          <ShieldOff className="h-6 w-6 text-amber-500 mx-auto" />
          <h1 className="text-lg font-semibold">Submit-Sprint is fixture-only</h1>
          <p className="text-sm muted leading-relaxed">
            This mode operates against LOCAL FIXTURE JOBS ONLY. Real employer forms are never used in sprint mode.
          </p>
          <button className="text-sm text-accent hover:underline" onClick={() => nav('/feed')} data-testid="sprint-blocked-back-to-feed">
            Back to feed
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto py-10 px-6 space-y-6" data-testid="sprint-page">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2">
            <Zap className="h-5 w-5 text-accent" />
            <span className="text-xs font-mono tracking-wide muted uppercase">Submit-Sprint · fixture</span>
          </div>
          <h1 className="text-2xl font-semibold text-ink dark:text-ink-dark mt-1">One-key confirm sprint</h1>
          <p className="text-sm muted mt-2 leading-relaxed max-w-lg">
            Press <kbd className="font-mono text-xs border border-line dark:border-line-dark rounded px-1.5 py-0.5">Enter</kbd> to confirm the next slot. Emergency stop halts the queue. Zero real-employer submissions — every completed slot writes a fixture-sprint receipt.
          </p>
        </div>
        {sprint && sprint.state === 'running' && (
          <button
            onClick={stop} disabled={busy}
            className="inline-flex items-center gap-2 rounded-md border border-red-500/40 text-red-700 dark:text-red-400 px-3 py-1.5 text-sm hover:bg-red-500/10 disabled:opacity-60"
            data-testid="sprint-emergency-stop"
          >
            <StopCircle className="h-4 w-4" /> Emergency stop
          </button>
        )}
      </div>

      {!sprint && (
        <div className="card p-5 space-y-3">
          <p className="text-sm text-ink dark:text-ink-dark">
            <span className="font-semibold">{apps.length}</span> fixture application(s) shortlisted and ready to sprint.
          </p>
          {apps.length === 0 ? (
            <p className="text-xs muted">Shortlist some SampleCo jobs on the /feed page first.</p>
          ) : (
            <ul className="text-xs muted space-y-1" data-testid="sprint-preview-list">
              {apps.slice(0, 20).map((a) => (
                <li key={a.id} className="truncate">
                  · {a.job_snapshot?.title || a.id} <span className="opacity-70">@ {a.job_snapshot?.company_name}</span>
                </li>
              ))}
            </ul>
          )}
          <button
            onClick={start} disabled={busy || apps.length === 0}
            className="inline-flex items-center gap-2 rounded-md bg-accent text-white px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-60"
            data-testid="sprint-start"
          >
            <Play className="h-4 w-4" /> Start sprint ({Math.min(apps.length, 20)} slot{apps.length === 1 ? '' : 's'})
          </button>
        </div>
      )}

      {error && (
        <div className="card p-3 flex items-start gap-2 border-red-500/30" data-testid="sprint-error">
          <AlertTriangle className="h-4 w-4 mt-0.5 text-red-700 dark:text-red-400" />
          <span className="text-sm text-red-700 dark:text-red-300">{error}</span>
        </div>
      )}

      {sprint && (
        <div className="card p-5 space-y-3" data-testid="sprint-active">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs muted">Sprint state</div>
              <div className="font-mono text-sm" data-testid="sprint-state">{sprint.state}</div>
            </div>
            <div className="text-right">
              <div className="text-xs muted">Progress</div>
              <div className="font-mono text-sm" data-testid="sprint-progress">
                {sprint.completed_slot_count}/{sprint.slots.length}
              </div>
            </div>
          </div>
          <ul className="space-y-2" data-testid="sprint-slots">
            {sprint.slots.map((slot, i) => (
              <li
                key={slot.slot_id}
                className={`rounded-md border p-3 text-sm flex items-center justify-between ${
                  slot.state === 'completed' ? 'border-accent/40 bg-accent/5'
                    : slot.state === 'queued' ? 'border-line dark:border-line-dark'
                    : 'border-red-500/30 bg-red-500/5'
                }`}
                data-testid={`sprint-slot-${i}`}
              >
                <div>
                  <div className="font-medium text-ink dark:text-ink-dark">{slot.job_title || slot.application_id}</div>
                  <div className="text-xs muted font-mono">{slot.state}{slot.receipt_id ? ` · receipt ${slot.receipt_id.slice(0, 8)}` : ''}</div>
                </div>
                {slot.state === 'queued' && sprint.state === 'running' && (
                  <button
                    onClick={() => confirmSlot(slot)}
                    disabled={busy}
                    className="inline-flex items-center gap-1 rounded-md bg-accent/10 text-accent px-2.5 py-1 text-xs font-medium hover:bg-accent/20 disabled:opacity-60"
                    data-testid={`sprint-slot-confirm-${i}`}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" /> Confirm
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
