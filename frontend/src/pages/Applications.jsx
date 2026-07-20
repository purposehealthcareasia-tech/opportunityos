import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Send, ExternalLink, ArrowRight, TestTube2, Clock, CheckCircle2, XCircle } from 'lucide-react';
import { api, withIdempotency } from '../lib/api';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import { LoadingBlock, ErrorBlock, EmptyBlock } from '../lib/scope';

const STATE_ORDER = [
  'shortlisted', 'preparing', 'awaiting_approval', 'approved',
  'submitting', 'submitted', 'response', 'interview', 'offer', 'closed',
];

const STATE_LABEL = {
  shortlisted: 'Shortlisted',
  preparing: 'Preparing',
  awaiting_approval: 'Awaiting your approval',
  approved: 'Approved to submit',
  submitting: 'Submitting',
  submitted: 'Submitted',
  response: 'Employer responded',
  interview: 'Interview',
  offer: 'Offer',
  closed: 'Closed',
};

// State machine echoing backend's allowed transitions. UI-only mirror.
const NEXT_ALLOWED = {
  shortlisted: ['preparing', 'closed'],
  preparing: ['awaiting_approval', 'closed'],
  awaiting_approval: ['approved', 'preparing', 'closed'],
  approved: ['submitting', 'closed'],
  submitting: ['submitted', 'closed'],
  submitted: ['response', 'closed'],
  response: ['interview', 'closed'],
  interview: ['offer', 'closed'],
  offer: ['closed'],
  closed: [],
};

function SampleBadge() {
  return (
    <span className="pill pill-neutral !bg-amber-500/10 !border-amber-500/30 !text-amber-700 dark:!text-amber-400 font-medium" data-testid="sample-badge">
      <TestTube2 className="h-3 w-3" /> SAMPLE
    </span>
  );
}

function StatePill({ state }) {
  const map = {
    shortlisted: 'pill pill-neutral',
    preparing: 'pill pill-neutral',
    awaiting_approval: 'pill border-amber-500/40 text-amber-700 dark:text-amber-400',
    approved: 'pill pill-accent',
    submitting: 'pill pill-neutral',
    submitted: 'pill pill-accent',
    response: 'pill pill-accent',
    interview: 'pill pill-accent',
    offer: 'pill pill-accent',
    closed: 'pill border-neutral-400/40 muted',
  };
  return <span className={map[state] || 'pill pill-neutral'} data-testid={`app-state-${state}`}>{STATE_LABEL[state] || state}</span>;
}

function TimelinePreview({ state }) {
  const key = STATE_ORDER.indexOf(state);
  return (
    <div className="flex items-center gap-1 mt-2">
      {STATE_ORDER.filter((s) => s !== 'closed').map((s, i) => (
        <div
          key={s}
          title={STATE_LABEL[s]}
          className={`h-1 flex-1 rounded-full ${i <= key ? 'bg-accent' : 'bg-neutral-200 dark:bg-neutral-800'}`}
        />
      ))}
    </div>
  );
}

function TransitionMenu({ app, onTransition, busy }) {
  const options = NEXT_ALLOWED[app.state] || [];
  if (options.length === 0) return null;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {options.map((next) => (
        <Button
          key={next}
          size="sm"
          variant={next === 'closed' ? 'ghost' : 'secondary'}
          loading={busy}
          onClick={() => onTransition(app, next)}
          data-testid={`app-transition-${app.id}-${next}`}
        >
          {next === 'closed' ? 'Close' : <>Move to {STATE_LABEL[next]}<ArrowRight className="h-3 w-3" /></>}
        </Button>
      ))}
    </div>
  );
}

export default function ApplicationsPage() {
  const [state, setState] = useState({ loading: true, error: null, apps: [] });
  const [busyId, setBusyId] = useState(null);
  const [flash, setFlash] = useState(null);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const { data } = await api.get('/api/v1/applications');
      setState({ loading: false, error: null, apps: data.applications || [] });
    } catch {
      setState({ loading: false, error: 'Could not load your applications.', apps: [] });
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const transition = async (app, newState) => {
    setBusyId(app.id);
    setFlash(null);
    try {
      await api.patch(`/api/v1/applications/${app.id}/state`,
        { expected_state: app.state, new_state: newState },
        withIdempotency(),
      );
      await load();
      setFlash({ kind: 'ok', msg: `${app.job_snapshot.title} → ${STATE_LABEL[newState]}` });
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (d?.error === 'state_precondition_failed') setFlash({ kind: 'warn', msg: 'State changed elsewhere — reloaded.' });
      else if (d?.error === 'invalid_transition') setFlash({ kind: 'err', msg: `Can't go ${d.from} → ${d.to}.` });
      else setFlash({ kind: 'err', msg: 'Transition failed.' });
      await load();
    } finally { setBusyId(null); }
  };

  // Founder Directive #7: exclude SAMPLE rows from user-facing counts/metrics.
  const real = useMemo(() => state.apps.filter((a) => !a.job_snapshot?.is_sample), [state.apps]);
  const sampleCount = state.apps.length - real.length;

  const byState = useMemo(() => {
    const m = {};
    for (const a of real) (m[a.state] ||= []).push(a);
    return m;
  }, [real]);

  if (state.loading) return <div className="max-w-4xl mx-auto"><LoadingBlock label="Loading applications…" /></div>;
  if (state.error) return <div className="max-w-4xl mx-auto"><ErrorBlock message={state.error} onRetry={load} /></div>;

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-fadeIn" data-testid="applications-page">
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2"><Send className="h-5 w-5" /> Applications</h1>
        <p className="muted text-sm mt-1 max-w-2xl">
          Real applications you've shortlisted. State transitions run through an atomic precondition check on the server — no fabricated stages, no phantom progress.
          {sampleCount > 0 && <> SAMPLE rows below are shown but never counted in your metrics.</>}
        </p>
      </div>

      {flash && (
        <div className={`rounded-md px-3 py-2 text-sm border ${
          flash.kind === 'ok' ? 'border-accent/40 bg-accent/5 text-accent'
          : flash.kind === 'warn' ? 'border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400'
          : 'border-red-500/40 bg-red-500/5 text-red-700 dark:text-red-400'
        }`}>{flash.msg}</div>
      )}

      <div className="grid md:grid-cols-4 gap-3">
        <div className="card p-4">
          <div className="text-xs muted">Open</div>
          <div className="text-2xl font-semibold mt-1" data-testid="applications-open-count">{real.filter((a) => a.state !== 'closed').length}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs muted">Submitted</div>
          <div className="text-2xl font-semibold mt-1">{(byState.submitted || []).length}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs muted">In interview</div>
          <div className="text-2xl font-semibold mt-1">{(byState.interview || []).length}</div>
        </div>
        <div className="card p-4">
          <div className="text-xs muted">Excluded SAMPLE rows</div>
          <div className="text-2xl font-semibold mt-1" data-testid="applications-sample-count">{sampleCount}</div>
          <div className="text-[10px] muted mt-1">Shown below but never counted here.</div>
        </div>
      </div>

      {state.apps.length === 0 ? (
        <EmptyBlock
          title="No applications yet"
          hint="Shortlist a job from the feed to start tracking it here."
          action={<Link to="/feed" className="btn btn-accent">Open the feed</Link>}
        />
      ) : (
        <div className="space-y-3" data-testid="applications-list">
          {state.apps.map((a) => (
            <div key={a.id} className="card p-5" data-testid={`application-row-${a.id}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Link to={`/jobs/${a.job_id}`} className="text-base font-semibold text-ink dark:text-ink-dark hover:underline">{a.job_snapshot?.title || 'Untitled'}</Link>
                    {a.job_snapshot?.is_sample && <SampleBadge />}
                    <StatePill state={a.state} />
                  </div>
                  <div className="text-xs muted mt-1 flex items-center gap-2">
                    <span>{a.job_snapshot?.company_name || '—'}</span>
                    <span>·</span>
                    <span className="font-mono">{a.route}</span>
                    <span>·</span>
                    <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" />{new Date(a.created_at).toLocaleString()}</span>
                  </div>
                  <TimelinePreview state={a.state} />
                </div>
                <div className="flex-shrink-0">
                  <TransitionMenu app={a} onTransition={transition} busy={busyId === a.id} />
                </div>
              </div>
              <p className="text-xs muted mt-3 leading-relaxed max-w-3xl">{a.route_rationale}</p>
            </div>
          ))}
        </div>
      )}

      <div className="rounded-card border border-line dark:border-line-dark p-4 text-xs muted leading-relaxed">
        <p><strong>Note.</strong> Submitting an application actually to an employer lands in Phase 5. Today the tracker records
        state changes with an atomic precondition — you can move things through the pipeline honestly, but no packets leave
        your account. When Phase 5 wires the submit path, each real submission will append an immutable receipt (already
        indexed on <code>(user, company, req_ref)</code> to prevent duplicates).</p>
      </div>
    </div>
  );
}
