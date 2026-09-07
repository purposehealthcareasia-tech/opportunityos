import React, { useEffect, useState } from 'react';
import { CheckCircle2, XCircle, Shield, Flag, Layers, AlertCircle,
         Activity, Globe2, ScrollText, ArrowUpRight } from 'lucide-react';
import { api } from '../lib/api';

/**
 * Phase 4 · /standards — PUBLIC measuring-state page.
 *
 * No auth required. No PII surfaced. Everything is a public aggregate.
 *
 * P0 Truth Audit (2026-08-13) sections added:
 *   - outcome_rows: median days-to-first-response, interviews per 100.
 *     Never-fabricate: below-threshold renders "measuring" with n.
 *   - verification_ladder: owner-attested → document-backed →
 *     third-party-checked; explains what "verified" means per tier.
 *   - per_country_coverage: real rows only, SAMPLE segregated,
 *     honest indeterminate bucket.
 *   - north_star: Time to Qualified Interview + guardrails baseline.
 *     Below-threshold renders "measuring (baseline)".
 */
export default function StandardsPage() {
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get('/api/v1/standards');
        if (!cancelled) setState({ loading: false, data, error: null });
      } catch (e) {
        if (!cancelled) setState({ loading: false, data: null,
          error: 'Failed to load standards.' });
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (state.loading) return <div className="p-6 muted">Loading measuring state…</div>;
  if (state.error || !state.data) return (
    <div className="p-6 text-red-600 flex items-center gap-2">
      <AlertCircle className="h-4 w-4" /> {state.error}
    </div>
  );
  const d = state.data;
  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6" data-testid="standards-page">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Fynd · Measuring state</h1>
        <p className="text-sm muted mt-1">{d.note}</p>
        <p className="text-xs muted font-mono mt-1">policy_text_version: {d.policy_text_version}</p>
      </header>

      <PhaseGates phases={d.phases_gated_pass} />
      <ChangeHistory items={d.change_history} />
      <Coverage cov={d.coverage} />
      <OutcomeRows rows={d.outcome_rows} />
      <VerificationLadder tiers={d.verification_ladder} />
      <PerCountry coverage={d.per_country_coverage} />
      <NorthStar ns={d.north_star} />
      <FeatureFlags flags={d.feature_flags} />
      <Rails rails={d.rails} />
    </div>
  );
}

function PhaseGates({ phases }) {
  return (
    <section className="card p-5 space-y-3" data-testid="standards-phases">
      <SectionHeader icon={Layers} title="Phase gates" />
      <ul className="space-y-1">
        {phases.map((p) => (
          <li key={p.phase} className="text-sm flex items-center gap-2"
              data-testid={`standards-phase-${p.phase.split(' ')[1] || p.phase.slice(0, 8)}`}>
            <CheckCircle2 className="h-4 w-4 text-accent" />
            <span className="font-medium">{p.phase}</span>
            <span className="pill pill-accent text-[10px]">{p.verdict}</span>
            <span className="muted font-mono ml-auto">{p.date}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ChangeHistory({ items }) {
  if (!items || !items.length) return null;
  return (
    <section className="card p-5 space-y-3" data-testid="standards-change-history">
      <SectionHeader icon={ScrollText} title="Change history (append-only)" />
      <ol className="space-y-2">
        {items.slice().reverse().map((row, idx) => (
          <li key={`${row.date}-${idx}`} className="text-xs" data-testid="standards-change-row">
            <span className="font-mono muted mr-2">{row.date}</span>
            <span>{row.change}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Coverage({ cov }) {
  return (
    <section className="card p-5 space-y-3" data-testid="standards-coverage">
      <SectionHeader icon={Shield} title="Coverage" />
      <div className="grid sm:grid-cols-4 gap-3 text-sm">
        <StatCell testid="standards-cov-providers" label="Verified providers" value={cov.verified_providers} />
        <StatCell testid="standards-cov-jobs" label="Jobs in index (real)" value={cov.jobs_in_index.toLocaleString()} />
        <StatCell testid="standards-cov-fresh" label="Fresh jobs" value={cov.fresh_jobs_in_index.toLocaleString()} />
        <StatCell testid="standards-cov-sample-excluded" label="SAMPLE rows excluded"
                  value={cov.sample_rows_excluded_from_public_counts?.toLocaleString?.() ?? 0} />
      </div>
    </section>
  );
}

function OutcomeRows({ rows }) {
  return (
    <section className="card p-5 space-y-3" data-testid="standards-outcome-rows">
      <SectionHeader icon={Activity} title="Outcome rows" />
      <p className="text-xs muted">
        Never fabricate. Below the honest-n threshold, the value renders <em>“measuring”</em> — not a synthesized number.
      </p>
      <div className="grid sm:grid-cols-2 gap-3 text-sm">
        <div data-testid="standards-outcome-median-response">
          <div className="text-xs muted uppercase tracking-wide">Median days to first response</div>
          <div className="text-2xl font-mono">{fmtMetric(rows.median_days_to_first_response)}</div>
          <div className="text-[11px] muted">
            n = {rows.honest_n_responses} · threshold ≥ {rows.never_fabricate_thresholds.median_days_to_first_response}
          </div>
        </div>
        <div data-testid="standards-outcome-interviews-per-100">
          <div className="text-xs muted uppercase tracking-wide">Interviews per 100 apps</div>
          <div className="text-2xl font-mono">{fmtMetric(rows.interviews_per_100_apps)}</div>
          <div className="text-[11px] muted">
            n_apps = {rows.honest_n_applications} · n_interviews = {rows.honest_n_interviews} · threshold ≥ {rows.never_fabricate_thresholds.interviews_per_100_apps}
          </div>
        </div>
      </div>
    </section>
  );
}

function VerificationLadder({ tiers }) {
  return (
    <section className="card p-5 space-y-3" data-testid="standards-verification-ladder">
      <SectionHeader icon={ArrowUpRight} title="Public claim-verification ladder" />
      <ol className="space-y-3">
        {tiers.map((t) => (
          <li key={t.tier} className="text-sm space-y-1"
              data-testid={`standards-tier-${t.tier}`}>
            <div className="flex items-center gap-2">
              <span className="pill pill-neutral text-[10px]">tier {t.tier}</span>
              <span className="font-semibold font-mono">{t.name}</span>
            </div>
            <p className="text-xs">{t.definition}</p>
            <p className="text-[11px] muted">
              <span className="font-mono">evidence:</span> {t.evidence}
            </p>
            <p className="text-[11px] muted">
              <span className="font-mono">employer_signal:</span> {t.employer_signal}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function PerCountry({ coverage }) {
  const c = coverage;
  return (
    <section className="card p-5 space-y-3" data-testid="standards-per-country">
      <SectionHeader icon={Globe2} title="Per-country coverage (India)" />
      <p className="text-xs muted">{c.note}</p>
      <div className="grid sm:grid-cols-2 gap-4 text-sm">
        <div data-testid="standards-per-country-cities">
          <div className="text-xs muted uppercase tracking-wide mb-2">India — by city (real rows)</div>
          <ul className="space-y-1">
            {Object.entries(c.india_by_city_real).map(([k, v]) => (
              <li key={k} className="flex justify-between text-sm">
                <span>{k}</span>
                <span className="font-mono">{v.toLocaleString()}</span>
              </li>
            ))}
            <li className="flex justify-between text-sm border-t border-white/10 pt-1 mt-1 font-semibold">
              <span>India total</span>
              <span className="font-mono">{c.india_total_real.toLocaleString()}</span>
            </li>
          </ul>
        </div>
        <div data-testid="standards-per-country-remote">
          <div className="text-xs muted uppercase tracking-wide mb-2">Remote (all sources) — real rows</div>
          <ul className="space-y-1">
            <li className="flex justify-between text-sm"><span>Total remote</span><span className="font-mono">{c.remote_classification_real.remote_total.toLocaleString()}</span></li>
            <li className="flex justify-between text-sm"><span>Classified US-only</span><span className="font-mono">{c.remote_classification_real.us_only.toLocaleString()}</span></li>
            <li className="flex justify-between text-sm"><span>Explicit India</span><span className="font-mono">{c.remote_classification_real.india_explicit.toLocaleString()}</span></li>
            <li className="flex justify-between text-sm"><span>Indeterminate</span><span className="font-mono">{c.remote_classification_real.indeterminate.toLocaleString()}</span></li>
          </ul>
        </div>
      </div>
      <p className="text-[11px] muted">
        SAMPLE rows excluded from every count: <span className="font-mono">{c.sample_rows_excluded}</span>.
      </p>
    </section>
  );
}

function NorthStar({ ns }) {
  return (
    <section className="card p-5 space-y-3" data-testid="standards-north-star">
      <SectionHeader icon={Activity} title="North-star baseline + guardrails" />
      <p className="text-xs muted">{ns.measurement_note}</p>
      <div className="grid sm:grid-cols-2 gap-3 text-sm">
        <div data-testid="standards-tqi">
          <div className="text-xs muted uppercase tracking-wide">Time to Qualified Interview (median days)</div>
          <div className="text-2xl font-mono">{fmtMetric(ns.time_to_qualified_interview_days_median)}</div>
          <div className="text-[11px] muted">
            users with interview = {ns.n_users_with_interview} · threshold ≥ {ns.never_fabricate_thresholds.tqi_median}
          </div>
        </div>
        <div data-testid="standards-guardrails">
          <div className="text-xs muted uppercase tracking-wide mb-1">Guardrails (n_apps = {ns.honest_n_applications} · threshold ≥ {ns.never_fabricate_thresholds.guardrail_baselines})</div>
          <ul className="space-y-0.5 text-xs">
            <li className="flex justify-between"><span>Application → response</span><span className="font-mono">{fmtMetric(ns.guardrails.application_to_response_rate)}</span></li>
            <li className="flex justify-between"><span>Response → interview</span><span className="font-mono">{fmtMetric(ns.guardrails.response_to_interview_rate)}</span></li>
            <li className="flex justify-between"><span>False-pass rate</span><span className="font-mono">{fmtMetric(ns.guardrails.false_pass_rate)}</span></li>
            <li className="flex justify-between"><span>False-exclusion rate</span><span className="font-mono">{fmtMetric(ns.guardrails.false_exclusion_rate)}</span></li>
            <li className="flex justify-between"><span>Duplicate rate</span><span className="font-mono">{fmtMetric(ns.guardrails.duplicate_rate)}</span></li>
            <li className="flex justify-between"><span>Closed-listing pool share</span><span className="font-mono">{fmtMetric(ns.guardrails.closed_listing_pool_share)}</span></li>
            <li className="flex justify-between"><span>Consent violations</span><span className="font-mono">{ns.guardrails.consent_violation_count}</span></li>
          </ul>
        </div>
      </div>
    </section>
  );
}

function FeatureFlags({ flags }) {
  return (
    <section className="card p-5 space-y-3" data-testid="standards-flags">
      <SectionHeader icon={Flag} title="Feature flags" />
      <ul className="space-y-1 text-sm">
        {flags.map((f) => (
          <li key={f.flag} className="flex items-center gap-2"
              data-testid={`standards-flag-${f.flag}`}>
            {f.enabled
              ? <CheckCircle2 className="h-4 w-4 text-accent" />
              : <XCircle className="h-4 w-4 muted" />}
            <span className="font-mono">{f.flag}</span>
            <span className="muted ml-auto">{f.note}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Rails({ rails }) {
  return (
    <section className="card p-5 space-y-3" data-testid="standards-rails">
      <SectionHeader icon={Shield} title="Safety rails" />
      <ul className="space-y-1 text-sm">
        {rails.map((r) => (
          <li key={r.rail} className="flex items-center gap-2"
              data-testid={`standards-rail-${r.rail.replace(/\s+/g, '-')}`}>
            <CheckCircle2 className="h-4 w-4 text-accent" />
            <span className="font-medium">{r.rail}</span>
            <span className="muted ml-auto">{r.state}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SectionHeader({ icon: Icon, title }) {
  return (
    <header className="flex items-center gap-2">
      <Icon className="h-4 w-4" />
      <h2 className="text-lg font-semibold">{title}</h2>
    </header>
  );
}

function StatCell({ label, value, testid }) {
  return (
    <div data-testid={testid}>
      <div className="text-xs muted uppercase tracking-wide">{label}</div>
      <div className="text-2xl font-mono">{value}</div>
    </div>
  );
}

function fmtMetric(v) {
  if (typeof v === 'number') return v.toLocaleString();
  return <span className="text-base muted italic">{String(v)}</span>;
}
