import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, BarChart3, Award, Timer } from 'lucide-react';
import { api } from '../lib/api';

/**
 * S17 — Analytics.
 *
 * Honesty rules (see backend `domains/analytics/service.py`):
 *  - Personal funnel counts REAL applications only; SAMPLE-seeded rows are shown separately.
 *  - No cohort/global stats — no cohort exists yet.
 *  - Empty state is explicit; nothing is fabricated.
 *  - Conversion rates use null (not 0%) when the denominator is 0.
 *  - minutes_to_prepare distribution is omitted when there are no data points.
 */

const FUNNEL_STAGES = ['prepared', 'submitted', 'response', 'interview', 'offer'];

export default function AnalyticsPage() {
  const [state, setState] = useState({ data: null, loading: true, error: null });

  const load = useCallback(async () => {
    setState({ data: null, loading: true, error: null });
    try {
      const res = await api.get('/api/v1/analytics/funnel');
      setState({ data: res.data, loading: false, error: null });
    } catch (e) {
      setState({ data: null, loading: false, error: e?.response?.data?.detail?.error || 'Failed to load analytics' });
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (state.loading) {
    return <div className="flex items-center gap-2 muted"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>;
  }
  if (state.error) {
    return <div className="rounded-md border border-red-400 bg-red-50 dark:bg-red-950 px-3 py-2 text-sm">{state.error}</div>;
  }

  const d = state.data;
  const conv = d.conversion || {};
  const empty = !!d.empty;

  return (
    <div className="space-y-8" data-testid="analytics-page">
      <header className="space-y-1">
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">Analytics</h1>
        <p className="muted max-w-3xl">
          Your personal funnel from REAL applications only. No cohort stats, no fabricated benchmarks —
          we won't compare you against a made-up "average user".
        </p>
      </header>

      {empty && (
        <div className="rounded-md border border-line dark:border-line-dark p-6 muted text-sm" data-testid="analytics-empty">
          {d.sample_note || 'No applications yet — start on the Feed and shortlist a role.'}
        </div>
      )}

      {!empty && (
        <section className="space-y-3" data-testid="analytics-funnel">
          <h2 className="text-lg font-semibold flex items-center gap-2"><BarChart3 className="h-4 w-4" /> Personal funnel</h2>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
            {FUNNEL_STAGES.map((stage) => (
              <div
                key={stage}
                className="rounded-md border border-line dark:border-line-dark p-3 space-y-1"
                data-testid={`funnel-stage-${stage}`}
              >
                <div className="text-xs uppercase tracking-wide muted">{stage}</div>
                <div className="text-2xl font-semibold">{d.totals[stage]}</div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-sm">
            {[
              ['Prepared → Submitted', conv.prepared_to_submitted],
              ['Submitted → Response', conv.submitted_to_response],
              ['Response → Interview', conv.response_to_interview],
              ['Interview → Offer',    conv.interview_to_offer],
            ].map(([label, pct]) => (
              <div
                key={label}
                className="rounded-md border border-line dark:border-line-dark p-3"
                data-testid={`conversion-${label.toLowerCase().replace(/[^a-z]+/g, '-')}`}
              >
                <div className="text-xs muted">{label}</div>
                <div className="text-xl font-semibold">
                  {pct === null || pct === undefined ? (
                    <span className="muted">—</span>
                  ) : (
                    `${pct}%`
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="space-y-3" data-testid="analytics-qi">
        <h2 className="text-lg font-semibold flex items-center gap-2"><Award className="h-4 w-4" /> Qualified interviews</h2>
        <div className="rounded-md border border-line dark:border-line-dark p-4 flex items-center justify-between">
          <div>
            <div className="text-3xl font-semibold">{d.qi_total}</div>
            <div className="text-xs muted">
              Interviews you flagged as "would you take the offer conversation?" — yes.
              We don't infer this from calendar signals or content; you confirm it explicitly.
            </div>
          </div>
        </div>
      </section>

      {d.minutes_to_prepare && (
        <section className="space-y-3" data-testid="analytics-prep-time">
          <h2 className="text-lg font-semibold flex items-center gap-2"><Timer className="h-4 w-4" /> Prepare-to-submit time</h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div className="rounded-md border border-line dark:border-line-dark p-3">
              <div className="text-xs muted">Data points</div>
              <div className="text-xl font-semibold">{d.minutes_to_prepare.count}</div>
            </div>
            <div className="rounded-md border border-line dark:border-line-dark p-3">
              <div className="text-xs muted">Fastest (min)</div>
              <div className="text-xl font-semibold">{d.minutes_to_prepare.min} min</div>
            </div>
            <div className="rounded-md border border-line dark:border-line-dark p-3">
              <div className="text-xs muted">Median</div>
              <div className="text-xl font-semibold">{d.minutes_to_prepare.median} min</div>
            </div>
            <div className="rounded-md border border-line dark:border-line-dark p-3">
              <div className="text-xs muted">Slowest (max)</div>
              <div className="text-xl font-semibold">{d.minutes_to_prepare.max} min</div>
            </div>
          </div>
        </section>
      )}

      {d.sample_note && (
        <div className="rounded-md border border-line dark:border-line-dark p-3 text-xs muted italic" data-testid="analytics-sample-note">
          {d.sample_note}
          {d.sample && (d.sample.prepared || 0) > 0 && (
            <span> · SAMPLE bucket: prepared={d.sample.prepared}, submitted={d.sample.submitted}.</span>
          )}
        </div>
      )}
    </div>
  );
}
