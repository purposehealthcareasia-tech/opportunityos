import React, { useCallback, useEffect, useState } from 'react';
import { Mail, Send, X, ShieldOff, Loader2 } from 'lucide-react';
import { api } from '../lib/api';
import { LoadingBlock, ErrorBlock } from '../lib/scope';

/**
 * Phase 1 §vii (1d) — Follow-up review lane.
 *
 * The lane is REVIEW-ONLY. Drafts never auto-send. Approve creates a
 * FRESH `email_outbox` row via the existing email-route dispatch
 * pipeline (still dry-run in preview). Discard is a terminal state.
 *
 * Rendered states (honest to backend contract):
 *   * loading
 *   * error (403 consent-revoked shown separately)
 *   * empty (no drafts yet)
 *   * list of drafts, filterable by state (draft / approved_and_dispatched / discarded)
 *   * per-draft approve dialog (destination + subject required)
 */
export default function FollowUps() {
  const [drafts, setDrafts] = useState(null);
  const [filter, setFilter] = useState('draft');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [approveFor, setApproveFor] = useState(null);   // draft object
  const [approveForm, setApproveForm] = useState({ destination: '', subject: '' });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const qs = filter && filter !== 'all' ? `?state=${filter}` : '';
      const { data } = await api.get(`/api/v1/follow-ups${qs}`);
      setDrafts(data.drafts || []);
    } catch (e) {
      if (e?.response?.status === 403) {
        setError({ kind: 'consent', message: 'Follow-up drafts need the "submit_applications" consent scope. Grant it in Settings.' });
      } else {
        setError({ kind: 'other', message: e?.response?.data?.detail || e.message || 'Could not load drafts.' });
      }
    } finally { setLoading(false); }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const openApprove = (d) => {
    setApproveFor(d);
    setApproveForm({ destination: '', subject: `Following up: ${d.body_preview?.split('\n', 1)[0]?.slice(0, 60) || 'my application'}` });
  };

  const doApprove = async () => {
    if (!approveFor) return;
    setBusyId(approveFor.id);
    try {
      await api.post(`/api/v1/follow-ups/${approveFor.id}/approve`, {
        destination: approveForm.destination.trim(),
        subject: approveForm.subject.trim(),
      });
      setApproveFor(null);
      await load();
    } catch (e) {
      alert(e?.response?.data?.detail?.error || e?.response?.data?.detail || e.message || 'Approve failed');
    } finally { setBusyId(null); }
  };

  const doDiscard = async (d) => {
    setBusyId(d.id);
    try {
      await api.post(`/api/v1/follow-ups/${d.id}/discard`);
      await load();
    } catch (e) {
      alert(e?.response?.data?.detail?.error || e?.response?.data?.detail || e.message || 'Discard failed');
    } finally { setBusyId(null); }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6" data-testid="follow-ups-page">
      <div>
        <h1 className="text-2xl font-semibold" data-testid="follow-ups-heading">Follow-up drafts</h1>
        <p className="text-sm muted mt-1">
          Review lane · <strong>never auto-sent</strong>. Approving a draft creates a fresh dry-run outbox entry (still preview-only). Discarding is terminal.
        </p>
      </div>

      <div className="flex items-center gap-2" data-testid="follow-ups-filter-tabs">
        {[
          { id: 'draft', label: 'Draft' },
          { id: 'approved_and_dispatched', label: 'Approved' },
          { id: 'discarded', label: 'Discarded' },
        ].map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setFilter(t.id)}
            className={`btn btn-sm ${filter === t.id ? 'btn-primary' : 'btn-ghost'}`}
            data-testid={`follow-ups-filter-${t.id}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && <LoadingBlock label="Loading follow-ups…" />}

      {error?.kind === 'consent' && (
        <div className="rounded-md border border-amber-500/25 bg-amber-500/5 p-3 text-xs flex items-start gap-2" data-testid="follow-ups-consent-required">
          <ShieldOff className="h-4 w-4 mt-0.5 text-amber-500" />
          <div>{error.message}</div>
        </div>
      )}
      {error?.kind === 'other' && <ErrorBlock message={String(error.message)} onRetry={load} />}

      {!loading && !error && drafts && drafts.length === 0 && (
        <div className="liquid-card p-6 text-center text-sm muted" data-testid="follow-ups-empty">
          No {filter === 'all' ? '' : filter.replace('_', ' ')} drafts yet. Once you submit an application, a follow-up is drafted at the right time — you'll review it here.
        </div>
      )}

      {!loading && !error && drafts && drafts.length > 0 && (
        <div className="space-y-3">
          {drafts.map((d) => (
            <div key={d.id} className="liquid-card p-4" data-testid="follow-up-draft-row">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Mail className="h-4 w-4 text-teal-500" />
                    <div className="text-sm font-medium" data-testid="follow-up-employer">{d.employer || '(unknown employer)'}</div>
                    <span className="text-[10px] muted uppercase tracking-wider" data-testid="follow-up-state">{d.state}</span>
                  </div>
                  <div className="text-xs muted mt-1">
                    Scheduled for <span data-testid="follow-up-scheduled-for">{new Date(d.scheduled_for).toLocaleDateString()}</span>
                    {' · '}
                    Timing source: <span data-testid="follow-up-median-source">{d.median_days_source === 'employer'
                      ? `employer median (${d.days_used}d)`
                      : `fallback 7d`}</span>
                  </div>
                  <pre className="mt-2 text-xs bg-black/5 dark:bg-white/5 rounded-md p-2 whitespace-pre-wrap font-mono max-h-40 overflow-y-auto" data-testid="follow-up-body-preview">{d.body_preview}</pre>
                </div>
                {d.state === 'draft' && (
                  <div className="flex flex-col gap-2 shrink-0">
                    <button
                      type="button"
                      disabled={busyId === d.id}
                      onClick={() => openApprove(d)}
                      className="btn btn-sm btn-primary"
                      data-testid="follow-up-approve"
                    >
                      <Send className="h-3.5 w-3.5" /> Approve
                    </button>
                    <button
                      type="button"
                      disabled={busyId === d.id}
                      onClick={() => doDiscard(d)}
                      className="btn btn-sm btn-ghost"
                      data-testid="follow-up-discard"
                    >
                      <X className="h-3.5 w-3.5" /> Discard
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Approve dialog */}
      {approveFor && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-labelledby="approve-dialog-title"
          data-testid="follow-up-approve-dialog"
        >
          <div className="liquid-card max-w-md w-full p-5 space-y-3">
            <h2 id="approve-dialog-title" className="text-base font-semibold">Approve follow-up</h2>
            <div className="text-xs muted">
              This creates a <strong>fresh outbox record</strong> via the same dispatch pipeline your normal sends use — preflight validator, dedup, throttle, dry-run in preview. No auto-send.
            </div>
            <div>
              <label className="text-xs muted">Recipient email</label>
              <input
                type="email"
                value={approveForm.destination}
                onChange={(e) => setApproveForm((f) => ({ ...f, destination: e.target.value }))}
                className="mt-1 w-full rounded-md border border-line dark:border-line-dark bg-transparent px-3 py-2 text-sm"
                placeholder="recruiter@example.com"
                data-testid="follow-up-approve-destination"
              />
            </div>
            <div>
              <label className="text-xs muted">Subject</label>
              <input
                type="text"
                value={approveForm.subject}
                onChange={(e) => setApproveForm((f) => ({ ...f, subject: e.target.value }))}
                className="mt-1 w-full rounded-md border border-line dark:border-line-dark bg-transparent px-3 py-2 text-sm"
                data-testid="follow-up-approve-subject"
              />
            </div>
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setApproveFor(null)}
                className="btn btn-sm btn-ghost"
                data-testid="follow-up-approve-cancel"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!approveForm.destination.trim() || !approveForm.subject.trim() || busyId === approveFor.id}
                onClick={doApprove}
                className="btn btn-sm btn-primary"
                data-testid="follow-up-approve-confirm"
              >
                {busyId === approveFor.id
                  ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Approving…</>
                  : <>Approve → dry-run outbox</>}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
