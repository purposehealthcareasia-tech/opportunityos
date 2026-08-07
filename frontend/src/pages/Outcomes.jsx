import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ListChecks,
  Undo2,
  Info,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Scale,
  Ban,
} from 'lucide-react';
import { api } from '../lib/api';
import { IntelligencePanel } from '../components/OutcomesIntelligence';

/**
 * Small readability helper — reallocation `group` may be an employer id
 * (UUID) or a `company::role` canonical key. We show:
 *   - canonical key → the employer segment (`acme::eng-role` → `acme`)
 *   - UUID          → shortened form (`e3a90842…f7`)
 *   - anything else → unchanged
 * The full string stays in the tooltip so the audit-truthful value is
 * always one hover away.
 */
function formatGroupLabel(group) {
  if (!group) return 'unknown';
  if (group.includes('::')) return group.split('::')[0];
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(group)) {
    return `${group.slice(0, 8)}…${group.slice(-2)}`;
  }
  return group;
}

/**
 * Outcomes surface — Phase 5.3.
 *
 * Two panels sitting side-by-side on wide screens:
 *
 * 1. Latest budget reallocation (read-only). Backed by
 *    `GET /api/v1/outcomes/reallocation/latest`. Renders the STORED
 *    `reason` strings verbatim — never recomputes on the client so we
 *    can't drift from the audit artifact.
 *
 * 2. Kill-list — active suppressions with per-row Restore CTA plus a
 *    recently-restored trail. Restore hits
 *    `POST /api/v1/outcomes/kill-list/{employer}/restore` and refreshes.
 *
 * Consent: both endpoints require the `track_applications` scope. A 403
 * bubbles up as a friendly "grant the scope" prompt (mirrors Tracker).
 */
export default function OutcomesPage() {
  const [state, setState] = useState({
    loading: true,
    error: null,
    consentBlocked: false,
    reallocation: null,
    reallocationMessage: null,
    active: [],
    restored: [],
  });
  const [restoringEmployer, setRestoringEmployer] = useState(null);
  const [flash, setFlash] = useState(null);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null, consentBlocked: false }));
    try {
      // Fire both requests in parallel — each is independently consent-gated.
      const [reallocRes, killRes] = await Promise.all([
        api.get('/api/v1/outcomes/reallocation/latest'),
        api.get('/api/v1/outcomes/kill-list'),
      ]);
      setState({
        loading: false, error: null, consentBlocked: false,
        reallocation: reallocRes.data?.reallocation || null,
        reallocationMessage: reallocRes.data?.message || null,
        active: killRes.data?.active || [],
        restored: killRes.data?.recently_restored || [],
      });
    } catch (e) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail;
      if (status === 403 && detail?.error === 'consent_required') {
        setState((s) => ({ ...s, loading: false, consentBlocked: true }));
        return;
      }
      setState((s) => ({
        ...s, loading: false,
        error: 'Failed to load outcome data. Please retry.',
      }));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const restore = async (employer) => {
    setRestoringEmployer(employer);
    setFlash(null);
    try {
      const { data } = await api.post(
        `/api/v1/outcomes/kill-list/${encodeURIComponent(employer)}/restore`,
        {},
      );
      setFlash({
        kind: 'ok',
        msg: `Restored ${employer}. Suppression cleared; the row is preserved on the audit trail.`,
        employer,
        restoredAt: data?.restored?.restored_at,
      });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setFlash({
        kind: 'err',
        msg: d?.error === 'kill_list_row_not_found'
          ? `${employer} is no longer on the kill-list.`
          : (d?.message || d?.error || 'Restore failed. Please retry.'),
      });
    } finally {
      setRestoringEmployer(null);
    }
  };

  if (state.consentBlocked) {
    return (
      <div className="space-y-4" data-testid="outcomes-consent-block">
        <h1 className="text-3xl font-semibold tracking-tight">Outcomes</h1>
        <div className="rounded-md border border-amber-400 bg-amber-50 dark:bg-amber-950 dark:text-amber-200 text-amber-900 px-4 py-3 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5" />
          <div className="text-sm">
            The outcomes surface needs the <strong>track_applications</strong> consent so we can persist and read your reallocation + kill-list state.
            {' '}Grant it under <Link to="/settings">Settings → Consent</Link>.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6 animate-fadeIn" data-testid="outcomes-page">
      <header>
        <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight flex items-center gap-2">
          <ListChecks className="h-6 w-6" /> Outcomes
        </h1>
        <p className="muted text-sm mt-1 max-w-3xl">
          Explainable, reversible allocation. This page reads stored artifacts verbatim — nothing is recomputed here, so what you see matches the audit trail.
        </p>
      </header>

      {flash && (
        <div
          className={`rounded-md px-3 py-2 text-sm border flex items-start gap-2 ${
            flash.kind === 'ok'
              ? 'border-accent/40 bg-accent/5 text-accent'
              : 'border-red-500/40 bg-red-500/5 text-red-700 dark:text-red-400'
          }`}
          data-testid="outcomes-flash"
        >
          {flash.kind === 'ok' ? <CheckCircle2 className="h-4 w-4 mt-0.5" /> : <AlertTriangle className="h-4 w-4 mt-0.5" />}
          <span>{flash.msg}</span>
        </div>
      )}

      {state.loading ? (
        <div className="flex items-center gap-2 muted" data-testid="outcomes-loading">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading outcomes…
        </div>
      ) : state.error ? (
        <div className="rounded-md border border-red-400 bg-red-50 dark:bg-red-950 px-3 py-2 text-sm" data-testid="outcomes-error">
          {state.error}{' '}
          <button type="button" onClick={load} className="underline ml-2" data-testid="outcomes-retry">Retry</button>
        </div>
      ) : (
        <>
          <div className="grid lg:grid-cols-2 gap-5">
            <ReallocationPanel
              reallocation={state.reallocation}
              message={state.reallocationMessage}
            />
            <KillListPanel
              active={state.active}
              restored={state.restored}
              onRestore={restore}
              restoringEmployer={restoringEmployer}
            />
          </div>
          {/* Phase 2 · INTELLIGENCE VISIBLE — read-only panels appended
              below the existing v1 surface. Independently consent-gated;
              renders its own consent-block message on 403. */}
          <IntelligencePanel />
        </>
      )}
    </div>
  );
}

function ReallocationPanel({ reallocation, message }) {
  if (!reallocation) {
    return (
      <section className="card p-5 space-y-3" data-testid="reallocation-empty">
        <header className="flex items-center gap-2">
          <Scale className="h-4 w-4" />
          <h2 className="text-lg font-semibold">Latest budget reallocation</h2>
        </header>
        <p className="text-sm muted">
          {message || 'No reallocation has been computed yet.'} As you record outcomes, the autopilot will compute a weighted allocation and stamp a stored reason on every group.
        </p>
      </section>
    );
  }
  const allocations = reallocation.allocations || [];
  return (
    <section className="card p-5 space-y-3" data-testid="reallocation-panel">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Scale className="h-4 w-4" /> Latest budget reallocation
        </h2>
        <span className="text-xs muted font-mono" data-testid="reallocation-computed-at">
          {new Date(reallocation.computed_at).toLocaleString()}
        </span>
      </header>
      <div className="text-xs muted flex items-center gap-3">
        <span data-testid="reallocation-window">window: {reallocation.window_days}d</span>
        <span>·</span>
        <span data-testid="reallocation-min-submits">min submits: {reallocation.min_group_submits}</span>
      </div>
      {allocations.length === 0 ? (
        <p className="text-sm muted italic" data-testid="reallocation-no-groups">
          No group met the minimum-submits threshold for this window. Nothing was reallocated.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="reallocation-list">
          {allocations.map((a) => (
            <li
              key={a.group}
              className="rounded-md border border-line dark:border-line-dark p-3 space-y-1"
              data-testid={`reallocation-row-${a.group}`}
            >
              <div className="flex items-center justify-between gap-2 text-sm">
                <span
                  className="font-mono truncate"
                  title={a.group}
                  data-testid={`reallocation-group-${a.group}`}
                >
                  {formatGroupLabel(a.group)}
                </span>
                <span
                  className="pill pill-accent text-xs flex-shrink-0"
                  data-testid={`reallocation-weight-${a.group}`}
                >
                  {(a.weight * 100).toFixed(1)}%
                </span>
              </div>
              <div className="text-xs muted flex items-center gap-3">
                <span>{a.submitted} submits</span>
                <span>·</span>
                <span>response rate {(a.response_rate * 100).toFixed(1)}%</span>
              </div>
              <div
                className="text-xs italic bg-neutral-50 dark:bg-neutral-900 border border-line dark:border-line-dark rounded px-2 py-1"
                data-testid={`reallocation-reason-${a.group}`}
              >
                <Info className="h-3 w-3 inline mr-1 -mt-0.5" />{a.reason}
              </div>
            </li>
          ))}
        </ul>
      )}
      <div className="text-[11px] muted italic pt-1 border-t border-line dark:border-line-dark">
        Read-only view. Reasons are surfaced verbatim from the audit artifact.
      </div>
    </section>
  );
}

function KillListPanel({ active, restored, onRestore, restoringEmployer }) {
  const nothingActive = active.length === 0;
  return (
    <section className="card p-5 space-y-3" data-testid="killlist-panel">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Ban className="h-4 w-4" /> Kill-list
        </h2>
        <span className="text-xs muted" data-testid="killlist-active-count">
          {active.length} active
        </span>
      </header>
      <p className="text-xs muted">
        Employers currently suppressed from your feed. Restore any row and the suppression clears immediately — the record is preserved for the audit trail.
      </p>
      {nothingActive ? (
        <p className="text-sm muted italic" data-testid="killlist-empty">
          No employers are currently on your kill-list.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="killlist-active">
          {active.map((row) => (
            <li
              key={row.id}
              className="rounded-md border border-line dark:border-line-dark p-3 flex items-start justify-between gap-2"
              data-testid={`killlist-row-${row.employer}`}
            >
              <div className="min-w-0 flex-1">
                <div className="font-medium text-sm truncate" data-testid={`killlist-employer-${row.employer}`}>
                  {row.employer}
                </div>
                <div className="text-xs muted italic mt-0.5" data-testid={`killlist-reason-${row.employer}`}>
                  {row.reason || 'no reason recorded'}
                </div>
                <div className="text-[11px] muted font-mono mt-1">
                  since {new Date(row.created_at).toLocaleString()}
                </div>
              </div>
              <button
                type="button"
                onClick={() => onRestore(row.employer)}
                disabled={restoringEmployer === row.employer}
                className="inline-flex items-center gap-1 rounded-md border border-line dark:border-line-dark px-2.5 py-1 text-xs font-medium hover:bg-neutral-100 dark:hover:bg-neutral-800 disabled:opacity-60"
                data-testid={`killlist-restore-${row.employer}`}
              >
                {restoringEmployer === row.employer
                  ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Restoring…</>
                  : <><Undo2 className="h-3.5 w-3.5" /> Restore</>}
              </button>
            </li>
          ))}
        </ul>
      )}

      {restored.length > 0 && (
        <div className="pt-2 border-t border-line dark:border-line-dark space-y-2" data-testid="killlist-recently-restored">
          <div className="text-xs muted uppercase tracking-wide">Recently restored</div>
          <ul className="space-y-1">
            {restored.map((row) => (
              <li
                key={row.id}
                className="text-xs muted flex items-center gap-2"
                data-testid={`killlist-restored-${row.employer}`}
              >
                <CheckCircle2 className="h-3 w-3 text-accent" />
                <span className="font-medium text-ink dark:text-ink-dark">{row.employer}</span>
                <span className="font-mono">— {new Date(row.restored_at).toLocaleString()}</span>
                <span className="italic">({row.restored_reason || 'user_restore'})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
