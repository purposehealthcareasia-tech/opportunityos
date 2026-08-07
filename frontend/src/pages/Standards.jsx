import React, { useEffect, useState } from 'react';
import { CheckCircle2, XCircle, Shield, Flag, Layers, AlertCircle } from 'lucide-react';
import { api } from '../lib/api';

/**
 * Phase 4 · /standards — PUBLIC measuring-state page.
 *
 * No auth required. No PII surfaced. Everything is a public aggregate:
 * verified provider count, ingested jobs in index, phase-gate verdicts,
 * feature-flag states, rail states.
 *
 * Consumers (auditors, partners, honest founders on adjacent products)
 * can hit this page without an account.
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

      <section className="card p-5 space-y-3" data-testid="standards-phases">
        <header className="flex items-center gap-2">
          <Layers className="h-4 w-4" />
          <h2 className="text-lg font-semibold">Phase gates</h2>
        </header>
        <ul className="space-y-1">
          {d.phases_gated_pass.map((p) => (
            <li key={p.phase} className="text-sm flex items-center gap-2"
                data-testid={`standards-phase-${p.phase.split(' ')[1]}`}>
              <CheckCircle2 className="h-4 w-4 text-accent" />
              <span className="font-medium">{p.phase}</span>
              <span className="pill pill-accent text-[10px]">{p.verdict}</span>
              <span className="muted font-mono ml-auto">{p.date}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card p-5 space-y-3" data-testid="standards-coverage">
        <header className="flex items-center gap-2">
          <Shield className="h-4 w-4" />
          <h2 className="text-lg font-semibold">Coverage</h2>
        </header>
        <div className="grid sm:grid-cols-3 gap-3 text-sm">
          <div data-testid="standards-cov-providers">
            <div className="text-xs muted uppercase tracking-wide">Verified providers</div>
            <div className="text-2xl font-mono">{d.coverage.verified_providers}</div>
          </div>
          <div data-testid="standards-cov-jobs">
            <div className="text-xs muted uppercase tracking-wide">Jobs in index</div>
            <div className="text-2xl font-mono">{d.coverage.jobs_in_index.toLocaleString()}</div>
          </div>
          <div data-testid="standards-cov-fresh">
            <div className="text-xs muted uppercase tracking-wide">Fresh jobs</div>
            <div className="text-2xl font-mono">{d.coverage.fresh_jobs_in_index.toLocaleString()}</div>
          </div>
        </div>
      </section>

      <section className="card p-5 space-y-3" data-testid="standards-flags">
        <header className="flex items-center gap-2">
          <Flag className="h-4 w-4" />
          <h2 className="text-lg font-semibold">Feature flags</h2>
        </header>
        <ul className="space-y-1 text-sm">
          {d.feature_flags.map((f) => (
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

      <section className="card p-5 space-y-3" data-testid="standards-rails">
        <header className="flex items-center gap-2">
          <Shield className="h-4 w-4" />
          <h2 className="text-lg font-semibold">Safety rails</h2>
        </header>
        <ul className="space-y-1 text-sm">
          {d.rails.map((r) => (
            <li key={r.rail} className="flex items-center gap-2"
                data-testid={`standards-rail-${r.rail.replace(/\s+/g, '-')}`}>
              <CheckCircle2 className="h-4 w-4 text-accent" />
              <span className="font-medium">{r.rail}</span>
              <span className="muted ml-auto">{r.state}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
