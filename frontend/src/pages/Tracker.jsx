import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Loader2, MailOpen, Copy, Check, AlertTriangle } from 'lucide-react';
import { api } from '../lib/api';

/**
 * S16 — Tracker.
 * Kanban with columns Prepared → Submitted → Response → Interview → Offer → Closed.
 * Cards move via manual "Log update" (append-only outcome + atomic state transition).
 * Consent gate: track_applications required; 403 surfaces a clear prompt.
 */

const COLUMN_ORDER = ['prepared', 'submitted', 'response', 'interview', 'offer', 'closed'];
const COLUMN_LABEL = {
  prepared: 'Prepared',
  submitted: 'Submitted',
  response: 'Response',
  interview: 'Interview',
  offer: 'Offer',
  closed: 'Closed',
};
const OUTCOME_OPTIONS = [
  { value: 'response', label: 'Response received' },
  { value: 'interview_request', label: 'Interview request' },
  { value: 'interview_scheduled', label: 'Interview scheduled' },
  { value: 'offer', label: 'Offer received' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'closed', label: 'Closed / withdrew' },
  { value: 'viewed', label: 'Just viewed (no state change)' },
];

export default function TrackerPage() {
  const [state, setState] = useState({ columns: null, loading: true, error: null, consentBlocked: false });
  const [forward, setForward] = useState(null);
  const [copyOK, setCopyOK] = useState(false);
  const [logFor, setLogFor] = useState(null);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null, consentBlocked: false }));
    try {
      const res = await api.get('/api/v1/tracker');
      setState({ columns: res.data.columns, loading: false, error: null, consentBlocked: false });
      try {
        const fa = await api.get('/api/v1/tracker/forward-address');
        setForward(fa.data);
      } catch (e) { console.debug('forward address fetch failed', e); }
    } catch (e) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail;
      if (status === 403 && detail?.error === 'consent_required') {
        setState({ columns: null, loading: false, error: null, consentBlocked: true });
      } else {
        setState({ columns: null, loading: false, error: 'Failed to load tracker', consentBlocked: false });
      }
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const copyForward = async () => {
    if (!forward) return;
    await navigator.clipboard.writeText(forward.address);
    setCopyOK(true);
    setTimeout(() => setCopyOK(false), 1500);
  };

  if (state.consentBlocked) {
    return (
      <div className="space-y-4" data-testid="tracker-consent-block">
        <h1 className="text-3xl font-semibold tracking-tight">Tracker</h1>
        <div className="rounded-md border border-amber-400 bg-amber-50 dark:bg-amber-950 dark:text-amber-200 text-amber-900 px-4 py-3 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5" />
          <div className="text-sm">
            The tracker needs the <strong>track_applications</strong> consent so we can persist your outcome timeline.
            {' '}Grant it under <Link to="/settings">Settings → Consent</Link>.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="tracker-page">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">Tracker</h1>
          <p className="muted max-w-3xl">
            Move cards by logging outcomes. Every event is an append-only ledger row; illegal jumps are rejected by the server.
          </p>
        </div>
        {forward && (
          <div className="rounded-md border border-line dark:border-line-dark p-3 text-xs w-full max-w-sm" data-testid="forward-address-box">
            <div className="flex items-center gap-2 muted mb-1">
              <MailOpen className="h-3.5 w-3.5" />
              Your forward address
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 truncate">{forward.address}</code>
              <button
                type="button"
                className="pill pill-neutral text-[10px] flex items-center gap-1"
                onClick={copyForward}
                data-testid="forward-address-copy"
              >
                {copyOK ? <Check className="h-3 w-3 text-accent" /> : <Copy className="h-3 w-3" />}
                {copyOK ? 'Copied' : 'Copy'}
              </button>
            </div>
            <div className="mt-1 text-[10px] muted italic" data-testid="forward-address-label">{forward.label}</div>
          </div>
        )}
      </header>

      {state.loading ? (
        <div className="flex items-center gap-2 muted"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
      ) : state.error ? (
        <div className="rounded-md border border-red-400 bg-red-50 dark:bg-red-950 px-3 py-2 text-sm">{state.error}</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3" data-testid="tracker-kanban">
          {COLUMN_ORDER.map((col) => {
            const cards = state.columns?.[col] || [];
            return (
              <div
                key={col}
                className="rounded-md border border-line dark:border-line-dark bg-neutral-50 dark:bg-neutral-900/40 p-2 min-h-[240px]"
                data-testid={`tracker-column-${col}`}
              >
                <div className="text-xs uppercase tracking-wide muted px-1 pb-2 flex items-center justify-between">
                  <span>{COLUMN_LABEL[col]}</span>
                  <span data-testid={`tracker-count-${col}`}>{cards.length}</span>
                </div>
                <ul className="space-y-2">
                  {cards.map((c) => (
                    <TrackerCard key={c.application_id} card={c} onLog={() => setLogFor(c)} />
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}

      {logFor && (
        <LogUpdateModal
          card={logFor}
          onClose={() => setLogFor(null)}
          onLogged={async () => { setLogFor(null); await load(); }}
        />
      )}
    </div>
  );
}

function TrackerCard({ card, onLog }) {
  const snap = card.job_snapshot || {};
  return (
    <li className="rounded-md bg-white dark:bg-neutral-900 border border-line dark:border-line-dark p-2 text-sm space-y-1" data-testid={`tracker-card-${card.application_id}`}>
      <div className="flex items-start gap-1 justify-between">
        <span className="font-medium truncate flex-1">{snap.title || 'Untitled'}</span>
        {snap.is_sample && <span className="pill pill-neutral text-[10px] flex-shrink-0">SAMPLE</span>}
      </div>
      <div className="text-xs muted truncate">{snap.company_name || 'Unknown'}</div>
      {card.latest_outcome && (
        <div className="text-xs">
          <span className="pill pill-neutral text-[10px]">{card.latest_outcome.event}</span>{' '}
          <span className="muted">{new Date(card.latest_outcome.ts).toLocaleDateString()}</span>
        </div>
      )}
      <div className="flex items-center gap-1 pt-1">
        <Link
          to={`/applications/${card.application_id}/prep`}
          className="text-xs pill pill-neutral no-underline"
          data-testid={`tracker-open-${card.application_id}`}
        >
          Open
        </Link>
        <button
          type="button"
          className="text-xs pill pill-neutral"
          onClick={onLog}
          data-testid={`tracker-log-update-${card.application_id}`}
        >
          Log update
        </button>
      </div>
    </li>
  );
}

function LogUpdateModal({ card, onClose, onLogged }) {
  const [event, setEvent] = useState('response');
  const [note, setNote] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      await api.post(`/api/v1/applications/${card.application_id}/outcomes`, { event, note: note || null });
      await onLogged();
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (d?.error === 'invalid_transition') {
        setError(`Illegal jump from "${d.from}" — allowed here: ${(d.allowed_from_here || []).join(', ') || 'none'}. The outcome was still recorded (append-only).`);
        // still refresh, because outcome IS persisted.
        setTimeout(() => onLogged(), 900);
      } else {
        setError(d?.message || d?.error || 'Failed to log update.');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 bg-black/40 flex items-center justify-center p-4" role="dialog" aria-modal="true" data-testid="log-update-modal">
      <div className="bg-white dark:bg-neutral-900 rounded-md border border-line dark:border-line-dark p-4 w-full max-w-md space-y-3">
        <h3 className="font-semibold">Log update</h3>
        <div className="text-xs muted">{card.job_snapshot?.company_name} · {card.job_snapshot?.title}</div>
        <label className="text-sm block">
          <div className="mb-1">Event</div>
          <select
            className="w-full rounded-md border border-line dark:border-line-dark bg-transparent p-2 text-sm"
            value={event}
            onChange={(e) => setEvent(e.target.value)}
            data-testid="log-update-event"
          >
            {OUTCOME_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
        <label className="text-sm block">
          <div className="mb-1">Note (optional)</div>
          <textarea
            rows={3}
            className="w-full rounded-md border border-line dark:border-line-dark bg-transparent p-2 text-sm"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            data-testid="log-update-note"
          />
        </label>
        {error && (
          <div className="rounded-md border border-amber-400 bg-amber-50 dark:bg-amber-950 dark:text-amber-200 text-amber-900 text-xs px-2 py-1.5" data-testid="log-update-error">
            {error}
          </div>
        )}
        <div className="flex items-center justify-end gap-2 pt-1">
          <button type="button" className="text-sm muted" onClick={onClose}>Cancel</button>
          <button type="button" className="btn-primary text-sm" onClick={submit} disabled={busy} data-testid="log-update-submit">
            {busy ? 'Logging…' : 'Log'}
          </button>
        </div>
      </div>
    </div>
  );
}
