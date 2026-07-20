import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Lock, Save, ShieldCheck, ShieldOff, AlertTriangle, Info } from 'lucide-react';
import { api, withIdempotency } from '../lib/api';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Input from '../components/ui/Input';
import { LoadingBlock, ErrorBlock, ScopeRequiredPrompt } from '../lib/scope';

const STATUSES = [
  { k: 'citizen', label: 'US citizen' },
  { k: 'permanent_resident', label: 'Permanent resident (green card)' },
  { k: 'ead_opt', label: 'EAD (OPT)' },
  { k: 'stem_opt', label: 'STEM OPT' },
  { k: 'h1b', label: 'H-1B' },
  { k: 'tn', label: 'TN' },
  { k: 'other', label: 'Other' },
  { k: 'unspecified', label: 'Prefer not to say (unspecified)' },
];

const US_PERSON = new Set(['citizen', 'permanent_resident']);
const NEEDS_SPONSORSHIP = new Set(['ead_opt', 'stem_opt', 'h1b', 'tn', 'other']);

function deriveClient(status) {
  return {
    itar_excluded: !US_PERSON.has(status) && status !== 'unspecified',
    e_verify_need: ['stem_opt', 'ead_opt', 'h1b', 'tn'].includes(status),
    sponsorship_need: NEEDS_SPONSORSHIP.has(status),
  };
}

function DateFieldsFor({ status, dates, setDates }) {
  const patch = (upd) => setDates({ ...(dates || {}), ...upd });
  if (status === 'ead_opt' || status === 'stem_opt') {
    return (
      <div className="grid md:grid-cols-2 gap-4">
        <Input type="date" label={status === 'stem_opt' ? 'STEM OPT end date' : 'OPT end date'} value={dates?.opt_end || ''} onChange={(e) => patch({ opt_end: e.target.value })} />
        <Input type="date" label="Earliest available start" value={dates?.earliest_start || ''} onChange={(e) => patch({ earliest_start: e.target.value })} />
      </div>
    );
  }
  if (status === 'h1b' || status === 'tn') {
    return (
      <div className="grid md:grid-cols-2 gap-4">
        <Input type="date" label="Current status valid through" value={dates?.status_valid_through || ''} onChange={(e) => patch({ status_valid_through: e.target.value })} />
        <Input type="date" label="Earliest available start" value={dates?.earliest_start || ''} onChange={(e) => patch({ earliest_start: e.target.value })} />
      </div>
    );
  }
  if (status === 'permanent_resident') {
    return (
      <div className="grid md:grid-cols-2 gap-4">
        <Input type="date" label="Permanent resident since (optional)" value={dates?.pr_since || ''} onChange={(e) => patch({ pr_since: e.target.value })} />
      </div>
    );
  }
  return null;
}

function FlagsPreview({ flags }) {
  const items = [
    { key: 'itar_excluded', label: 'ITAR / export-control excluded', bad: true },
    { key: 'e_verify_need', label: 'E-Verify likely required', bad: false },
    { key: 'sponsorship_need', label: 'Needs employer sponsorship', bad: false },
  ];
  return (
    <div className="grid md:grid-cols-3 gap-3">
      {items.map((i) => (
        <div key={i.key} className={`card p-4 border ${flags[i.key] ? (i.bad ? 'border-red-500/40' : 'border-accent/40') : ''}`}>
          <div className="flex items-center gap-2">
            {flags[i.key] ? <ShieldOff className={`h-4 w-4 ${i.bad ? 'text-red-500' : 'text-accent'}`} /> : <ShieldCheck className="h-4 w-4 muted" />}
            <span className="text-sm font-medium">{i.label}</span>
          </div>
          <p className="text-xs muted mt-1">{flags[i.key] ? 'Flag is ON for this status.' : 'Flag is off.'}</p>
        </div>
      ))}
    </div>
  );
}

function CoveragePanel() {
  const [state, setState] = useState({ loading: true, error: '', data: null, needsScope: false });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: '', needsScope: false }));
    try {
      const { data } = await api.get('/api/v1/eligibility/coverage-preview');
      setState({ loading: false, error: '', data, needsScope: false });
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') {
        setState({ loading: false, error: '', data: null, needsScope: true });
      } else {
        setState({ loading: false, error: 'Could not load coverage preview.', data: null, needsScope: false });
      }
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (state.loading) return <LoadingBlock label="Computing coverage…" />;
  if (state.needsScope) {
    return (
      <ScopeRequiredPrompt
        scope="discover_jobs"
        description="Coverage preview counts how many live jobs your current eligibility unlocks or excludes. It only runs after you grant discover_jobs."
        onGranted={load}
      />
    );
  }
  if (state.error) return <ErrorBlock message={state.error} onRetry={load} />;
  const d = state.data;
  const totals = d.totals || {};
  const excludedByReason = totals.excluded_by_reason || {};
  const reasonLabels = {
    requires_us_person: 'US-person requirement (ITAR)',
    no_sponsorship_offered: 'No sponsorship offered',
    work_auth_mismatch: 'Work-auth allow-list mismatch',
  };
  const failing = (d.jobs || []).filter((j) => !j.pass_all);
  return (
    <div className="space-y-4">
      <div className="grid md:grid-cols-3 gap-3">
        <div className="card p-4">
          <div className="text-xs muted">Live jobs</div>
          <div className="text-2xl font-semibold mt-1">{totals.live_jobs ?? 0}</div>
          <div className="text-[11px] muted mt-1">Includes {totals.sample_passing ?? 0} sample jobs — badged, never counted in production cohorts.</div>
        </div>
        <div className="card p-4 border-accent/40">
          <div className="text-xs muted">Passing all gates</div>
          <div className="text-2xl font-semibold mt-1">{totals.passing ?? 0}</div>
          <div className="text-[11px] muted mt-1">Real / sample: {totals.real_passing ?? 0} / {totals.sample_passing ?? 0}</div>
        </div>
        <div className="card p-4 border-red-500/40">
          <div className="text-xs muted">Excluded</div>
          <div className="text-2xl font-semibold mt-1">{Object.values(excludedByReason).reduce((a, b) => a + b, 0)}</div>
          <div className="text-[11px] muted mt-1">{Object.entries(excludedByReason).map(([k, v]) => `${reasonLabels[k] || k}: ${v}`).join(' · ') || 'None'}</div>
        </div>
      </div>

      {failing.length > 0 && (
        <Card>
          <CardHeader title="Excluded jobs (with reason codes)" subtitle="Sample jobs are labeled. Real employers land here in Phase 3." />
          <ul className="divide-y divide-line dark:divide-line-dark">
            {failing.map((j) => (
              <li key={j.job_id} className="py-3 flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">{j.title}{j.is_sample && <span className="ml-2 pill pill-neutral">SAMPLE</span>}</div>
                  <div className="text-xs muted mt-0.5">{j.canonical_key}</div>
                </div>
                <div className="flex flex-wrap gap-1 justify-end">
                  {j.fail_reasons.map((r) => (
                    <span key={r} className="pill border-red-500/40 text-red-600 dark:text-red-400"><AlertTriangle className="h-3 w-3" />{reasonLabels[r] || r}</span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export default function EligibilityPage() {
  const [status, setStatus] = useState('unspecified');
  const [dates, setDates] = useState({});
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [savedAt, setSavedAt] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const { data } = await api.get('/api/v1/eligibility/me');
      setStatus(data.status || 'unspecified');
      setDates(data.dates || {});
      setVersion(data.version || 0);
      setSavedAt(data.updated_at);
    } catch (e) {
      setError('Could not load your eligibility profile.');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const derivedClient = useMemo(() => deriveClient(status), [status]);

  const save = async () => {
    setSaving(true); setError('');
    try {
      const { data } = await api.post('/api/v1/eligibility', { status, dates }, withIdempotency());
      setVersion(data.version);
      setSavedAt(data.updated_at);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      setError(detail?.error === 'consent_required' ? 'You need process_career_data consent to save eligibility.' : 'Could not save eligibility.');
    } finally { setSaving(false); }
  };

  if (loading) return <div className="max-w-3xl mx-auto"><LoadingBlock label="Loading eligibility…" /></div>;

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fadeIn">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2"><Lock className="h-5 w-5 text-accent" /> Eligibility</h1>
          <p className="muted text-sm mt-1 max-w-2xl">Work-authorization status and visa timelines. This profile is sealed — admin and support see it masked; only you see the real values.</p>
        </div>
        <div className="text-xs muted">Version {version}{savedAt ? ` · saved ${new Date(savedAt).toLocaleString()}` : ''}</div>
      </div>

      <div className="card p-4 border-accent/30 bg-accent/5">
        <div className="flex items-start gap-3">
          <Info className="h-4 w-4 text-accent flex-shrink-0 mt-0.5" />
          <p className="text-sm">This is not legal advice. Encoded gates are heuristics based on how listings word their eligibility requirements. Always confirm with the employer.</p>
        </div>
      </div>

      {error && <ErrorBlock message={error} onRetry={load} />}

      <Card>
        <CardHeader title="Work-authorization status" subtitle="Pick the one that best describes you. Choose 'Prefer not to say' to keep everything masked while still using the product." />
        <div className="grid md:grid-cols-2 gap-2">
          {STATUSES.map((s) => (
            <button key={s.k} type="button" onClick={() => setStatus(s.k)} className={`rounded-md border px-3 py-2.5 text-left text-sm transition-colors ${status === s.k ? 'border-accent bg-accent/5' : 'border-line dark:border-line-dark muted hover:text-ink dark:hover:text-ink-dark'}`}>
              <div className="font-medium text-ink dark:text-ink-dark">{s.label}</div>
              <div className="text-[11px] muted mt-0.5">status: <span className="font-mono">{s.k}</span></div>
            </button>
          ))}
        </div>
        <div className="mt-5">
          <DateFieldsFor status={status} dates={dates} setDates={setDates} />
        </div>
      </Card>

      <Card>
        <CardHeader title="Derived flags preview" subtitle="Computed from the status you picked. Server recomputes on save." />
        <FlagsPreview flags={derivedClient} />
      </Card>

      <div className="flex items-center justify-end gap-3">
        <Button variant="accent" onClick={save} loading={saving}><Save className="h-4 w-4" /> Save & preview coverage</Button>
      </div>

      <div className="pt-4">
        <h2 className="text-lg font-semibold mb-3">Coverage preview</h2>
        <p className="muted text-sm mb-4 max-w-2xl">How many live jobs your current profile unlocks or excludes — with reason codes per exclusion. Live jobs count includes badged SAMPLE rows for observability; they never count in production cohorts.</p>
        <CoveragePanel key={version} />
      </div>
    </div>
  );
}
