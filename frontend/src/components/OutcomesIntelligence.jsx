import React, { useEffect, useState } from 'react';
import {
  Activity, Zap, MailCheck, Search, AlertCircle, Loader2,
} from 'lucide-react';
import { api } from '../lib/api';

/**
 * Phase 2 · INTELLIGENCE VISIBLE (read-only) — three panels appended to
 * the Outcomes page:
 *
 *   1. Twin sparklines: employer response drift (weekly medians) +
 *      AAB lag (daily averages).
 *   2. Weekly outcome digest (in-app render; email dispatch is behind
 *      the WEEKLY_DIGEST_EMAIL_ENABLED backend flag).
 *   3. Rejection autopsy — descriptive-only per-employer histogram.
 *
 * All three surfaces:
 *   - Are gated on the `track_applications` consent scope
 *     (parent OutcomesPage renders the consent-block message; we
 *      surface a 403 by mounting a compact inline notice instead).
 *   - Render honest empty states — never fabricate a number.
 *   - Draw SVG sparklines inline (no chart library, no external assets).
 */
export function IntelligencePanel() {
  const [state, setState] = useState({
    loading: true,
    error: null,
    consentBlocked: false,
    sparklines: null,
    digest: null,
    autopsy: null,
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [sp, dg, ap] = await Promise.all([
          api.get('/api/v1/outcomes/sparklines'),
          api.get('/api/v1/outcomes/digest/weekly'),
          api.get('/api/v1/outcomes/rejection-autopsy'),
        ]);
        if (cancelled) return;
        setState({
          loading: false, error: null, consentBlocked: false,
          sparklines: sp.data, digest: dg.data, autopsy: ap.data,
        });
      } catch (e) {
        if (cancelled) return;
        const status = e?.response?.status;
        const detail = e?.response?.data?.detail;
        if (status === 403 && detail?.error === 'consent_required') {
          setState((s) => ({ ...s, loading: false, consentBlocked: true }));
          return;
        }
        setState((s) => ({ ...s, loading: false,
          error: 'Failed to load intelligence panels.' }));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (state.loading) {
    return (
      <div className="flex items-center gap-2 muted text-sm" data-testid="intelligence-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading intelligence…
      </div>
    );
  }
  if (state.consentBlocked) {
    return (
      <div className="card p-4 border border-amber-400 bg-amber-50 dark:bg-amber-950 text-amber-900 dark:text-amber-200 text-sm flex items-start gap-2"
           data-testid="intelligence-consent-block">
        <AlertCircle className="h-4 w-4 mt-0.5" />
        <span>Intelligence panels need the <strong>track_applications</strong> consent. Grant it under Settings → Consent.</span>
      </div>
    );
  }
  if (state.error) {
    return (
      <div className="card p-4 border border-red-400 bg-red-50 dark:bg-red-950 text-red-900 dark:text-red-200 text-sm" data-testid="intelligence-error">
        {state.error}
      </div>
    );
  }
  return (
    <div className="space-y-5" data-testid="intelligence-panels">
      <SparklinesCard data={state.sparklines} />
      <WeeklyDigestCard data={state.digest} />
      <RejectionAutopsyCard data={state.autopsy} />
    </div>
  );
}

// ---------------------------------------------------------------------
// 1 · Sparklines — pure-SVG, no chart lib.
// ---------------------------------------------------------------------

function Sparkline({ values, width = 220, height = 44, label }) {
  // `values` is an array; nulls mean "no sample this bucket" — render
  // a gap. We never interpolate through gaps (audit-honest).
  const numeric = values.map((v) => (typeof v === 'number' ? v : null));
  const nonNulls = numeric.filter((v) => v !== null);
  if (nonNulls.length === 0) {
    return (
      <div className="h-11 flex items-center text-xs muted italic"
           data-testid={`sparkline-empty-${label}`}>
        no data in window
      </div>
    );
  }
  const min = Math.min(...nonNulls);
  const max = Math.max(...nonNulls);
  const range = max - min || 1;
  const stepX = width / Math.max(numeric.length - 1, 1);
  const y = (v) => height - 4 - ((v - min) / range) * (height - 12);

  // Build path with gaps.
  let path = '';
  let started = false;
  numeric.forEach((v, i) => {
    if (v == null) { started = false; return; }
    const px = i * stepX;
    const py = y(v);
    path += (!started ? `M ${px} ${py}` : ` L ${px} ${py}`);
    started = true;
  });
  return (
    <svg width={width} height={height}
         className="text-accent"
         data-testid={`sparkline-${label}`}
         aria-label={`${label} sparkline`}>
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" />
      {/* dots on real samples so gaps read clearly */}
      {numeric.map((v, i) => v == null ? null : (
        <circle key={i} cx={i * stepX} cy={y(v)} r="2" fill="currentColor" />
      ))}
    </svg>
  );
}

function SparklinesCard({ data }) {
  const rd = data?.employer_response_drift;
  const aa = data?.aab_lag;
  return (
    <section className="card p-5 space-y-4" data-testid="sparklines-card">
      <header className="flex items-center gap-2">
        <Activity className="h-4 w-4" />
        <h2 className="text-lg font-semibold">Response drift &amp; AAB lag</h2>
      </header>
      <div className="grid sm:grid-cols-2 gap-5">
        <div data-testid="sparkline-response-drift">
          <div className="text-xs muted mb-1">
            Employer response drift · {rd?.window}
          </div>
          <Sparkline
            values={(rd?.buckets || []).map((b) => b.median_days_to_response)}
            label="response-drift"
          />
          <div className="text-[11px] muted italic mt-1">
            {rd?.note || 'Median days to response, weekly.'}
          </div>
        </div>
        <div data-testid="sparkline-aab-lag">
          <div className="text-xs muted mb-1">
            Apply-at-Birth lag · {aa?.window}
          </div>
          <Sparkline
            values={(aa?.buckets || []).map((b) => b.avg_lag_hours)}
            label="aab-lag"
          />
          <div className="text-[11px] muted italic mt-1">
            {aa?.note || 'Avg hours from job discovery to AAB queue.'}
          </div>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------
// 2 · Weekly digest (in-app)
// ---------------------------------------------------------------------

function WeeklyDigestCard({ data }) {
  if (!data) return null;
  const { period, applications_submitted, events, median_response_days,
          response_sample_size, email_dispatch } = data;
  const row = (label, value, testid) => (
    <div className="flex items-center justify-between text-sm py-1"
         data-testid={`digest-row-${testid}`}>
      <span className="muted">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
  return (
    <section className="card p-5 space-y-3" data-testid="weekly-digest-card">
      <header className="flex items-center gap-2 justify-between">
        <div className="flex items-center gap-2">
          <MailCheck className="h-4 w-4" />
          <h2 className="text-lg font-semibold">Weekly digest</h2>
        </div>
        <span className="text-xs muted font-mono" data-testid="digest-period">
          {period.start} → {period.end}
        </span>
      </header>
      <div className="grid sm:grid-cols-2 gap-x-6">
        {row('Applications submitted', applications_submitted, 'apps-submitted')}
        {row('Responses received', events.response, 'events-response')}
        {row('Interview requests', events.interview_request, 'events-interview-request')}
        {row('Interviews scheduled', events.interview_scheduled, 'events-interview-scheduled')}
        {row('Rejections', events.rejected, 'events-rejected')}
        {row('Offers', events.offer, 'events-offer')}
      </div>
      <div className="text-xs muted flex items-center gap-2 pt-1 border-t border-line dark:border-line-dark"
           data-testid="digest-response-median">
        <Zap className="h-3.5 w-3.5" />
        {median_response_days == null
          ? <span className="italic">No response events yet this week.</span>
          : <span>Median response this week: <strong>{median_response_days}d</strong> ({response_sample_size} samples)</span>}
      </div>
      <div className="text-[11px] muted italic border-t border-line dark:border-line-dark pt-2"
           data-testid="digest-email-dispatch-notice">
        Email dispatch: {email_dispatch?.enabled ? 'ENABLED' : 'OFF (in-app render only)'}. {email_dispatch?.note}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------
// 3 · Rejection autopsy (descriptive only)
// ---------------------------------------------------------------------

const CATEGORY_LABELS = {
  no_reason_given: 'No reason recorded',
  rejection_after_screen: 'After phone screen',
  rejection_after_interview: 'After interview',
  rejection_experience_mismatch: 'Experience mismatch',
  rejection_credential_mismatch: 'Credential mismatch',
  rejection_location_mismatch: 'Location mismatch',
  rejection_visa_or_status: 'Visa / status',
  other: 'Other',
};

function RejectionAutopsyCard({ data }) {
  if (!data) return null;
  const { total_rejections, employers = [], categories = {}, note } = data;
  return (
    <section className="card p-5 space-y-3" data-testid="rejection-autopsy-card">
      <header className="flex items-center gap-2">
        <Search className="h-4 w-4" />
        <h2 className="text-lg font-semibold">Rejection autopsy</h2>
        <span className="ml-auto text-xs muted font-mono" data-testid="autopsy-total">
          {total_rejections} rejections · 180d window
        </span>
      </header>
      {total_rejections === 0 ? (
        <p className="text-sm muted italic" data-testid="autopsy-empty">{note}</p>
      ) : (
        <>
          <div className="text-xs muted grid grid-cols-2 sm:grid-cols-4 gap-1"
               data-testid="autopsy-categories">
            {Object.entries(categories).map(([k, v]) => (
              <div key={k} className="flex items-center gap-1"
                   data-testid={`autopsy-category-${k}`}>
                <span className="pill pill-neutral text-[10px]">{v}</span>
                <span>{CATEGORY_LABELS[k] || k}</span>
              </div>
            ))}
          </div>
          <ul className="space-y-2" data-testid="autopsy-employer-list">
            {employers.map((e) => (
              <li key={e.employer}
                  className="rounded-md border border-line dark:border-line-dark p-3"
                  data-testid={`autopsy-employer-${e.employer}`}>
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">{e.employer}</span>
                  <span className="pill pill-neutral text-xs">{e.count}</span>
                </div>
                <div className="text-xs muted mt-1 flex flex-wrap gap-1.5">
                  {Object.entries(e.categories).map(([k, v]) => (
                    <span key={k} className="pill pill-neutral text-[10px]"
                          data-testid={`autopsy-employer-${e.employer}-cat-${k}`}>
                      {CATEGORY_LABELS[k] || k} × {v}
                    </span>
                  ))}
                </div>
                {e.most_recent_ts && (
                  <div className="text-[11px] muted font-mono mt-1">
                    most recent · {new Date(e.most_recent_ts).toLocaleString()}
                  </div>
                )}
              </li>
            ))}
          </ul>
          <div className="text-[11px] muted italic border-t border-line dark:border-line-dark pt-2"
               data-testid="autopsy-copy-guardrail">
            {note}
          </div>
        </>
      )}
    </section>
  );
}
