import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  ArrowLeft, Building2, MapPin, ExternalLink, ShieldCheck, ShieldOff,
  HelpCircle, Send, EyeOff, TestTube2, CheckCircle2, XCircle, Clock, Sparkles,
} from 'lucide-react';
import { api, withIdempotency } from '../lib/api';
import { safeExternalHref } from '../lib/utils';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Input from '../components/ui/Input';
import { LoadingBlock, ErrorBlock } from '../lib/scope';
import { MatchExplainModal } from './Feed';

const REASON_LABELS = {
  requires_us_person: 'US-person required (ITAR)',
  no_sponsorship_offered: 'No sponsorship offered',
  work_auth_mismatch: 'Work-auth mismatch',
  work_auth_unspecified: 'Work-auth unspecified',
  below_salary_floor: 'Below your salary floor',
  location_mismatch: 'Location mismatch',
  employer_excluded: 'On your exclude list',
  experience_below_band: 'Below years-of-experience band',
  education_below_requirement: 'Below education requirement',
  stem_opt_expires_soon: 'STEM OPT expires too soon',
  duplicate_application: 'You already applied',
  job_not_live: 'Not currently live',
  job_stale: 'Not verified recently',
  experience_missing: 'Experience dates missing',
  clearance_unknown: 'Clearance unknown',
  licensure_gap: 'License gap',
  sponsorship_unknown: 'Sponsorship unstated',
  education_unknown: 'Education claim missing',
  location_unknown: 'Location unstated',
  no_comp_posted: 'No comp posted',
  stem_opt_end_missing: 'STEM OPT end missing',
  stem_opt_end_unparseable: 'STEM OPT end unparseable',
};
const rl = (c) => REASON_LABELS[c] || c;

function SampleBadge() {
  return (
    <span className="pill pill-neutral !bg-amber-500/10 !border-amber-500/30 !text-amber-700 dark:!text-amber-400 font-medium" data-testid="sample-badge">
      <TestTube2 className="h-3 w-3" /> SAMPLE
    </span>
  );
}

function GateRow({ g }) {
  const map = {
    pass: { Icon: CheckCircle2, cls: 'text-accent' },
    fail: { Icon: XCircle, cls: 'text-red-500' },
    unknown: { Icon: HelpCircle, cls: 'muted' },
  };
  const cfg = map[g.status] || map.unknown;
  const Icon = cfg.Icon;
  return (
    <li className="flex items-start gap-3 py-2 border-b border-line dark:border-line-dark last:border-0" data-testid={`gate-row-${g.name}`}>
      <Icon className={`h-4 w-4 flex-shrink-0 mt-0.5 ${cfg.cls}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <span className="font-medium text-sm">{g.name.replaceAll('_', ' ')}</span>
          <span className={`text-xs font-mono ${cfg.cls}`}>{g.status.toUpperCase()}</span>
        </div>
        {(g.reason || g.detail) && (
          <p className="text-xs muted mt-0.5">
            {g.reason && <span className="font-mono">{rl(g.reason)}</span>}
            {g.reason && g.detail && ' — '}
            {g.detail}
          </p>
        )}
      </div>
    </li>
  );
}

function ResolveOriginForm({ jobId, onResolved }) {
  const [url, setUrl] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const { data } = await api.post(`/api/v1/jobs/${jobId}/resolve`, { origin_url: url, notes: notes || null }, withIdempotency());
      onResolved?.(data);
    } catch (e2) {
      const d = e2?.response?.data?.detail;
      if (d?.error === 'route_unavailable_platform_policy') setError({ kind: 'platform', host: d.host });
      else if (d?.error === 'invalid_url') setError({ kind: 'invalid' });
      else setError({ kind: 'unknown' });
    } finally { setBusy(false); }
  };
  return (
    <Card>
      <CardHeader title="Resolve to the employer's original posting" subtitle="This URL needs to point at the employer's own careers page or ATS (not an aggregator)." />
      <form onSubmit={submit} className="space-y-3">
        <Input label="Employer posting URL" type="url" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} data-testid="resolve-url-input" />
        <Input label="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        {error?.kind === 'platform' && <ErrorBlock message={`We don't operate on ${error.host}. Provide the employer's own URL.`} />}
        {error?.kind === 'invalid' && <ErrorBlock message="Invalid URL." />}
        {error?.kind === 'unknown' && <ErrorBlock message="Resolve failed." />}
        <div className="flex justify-end">
          <Button variant="accent" type="submit" loading={busy} data-testid="resolve-submit">Resolve</Button>
        </div>
      </form>
    </Card>
  );
}

export default function JobDetailPage() {
  const { jobId } = useParams();
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState(null);
  const [explainOpen, setExplainOpen] = useState(false);
  const nav = useNavigate();

  const load = useCallback(async () => {
    setError('');
    try {
      const { data } = await api.get(`/api/v1/jobs/${jobId}`);
      setJob(data);
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (d?.error === 'consent_required') setError('Grant discover_jobs to view job details.');
      else if (d === 'job_not_found') setError('Job not found.');
      else setError('Could not load this job.');
    }
  }, [jobId]);
  useEffect(() => { load(); }, [load]);

  const shortlist = async () => {
    setBusy(true);
    try {
      await api.post(`/api/v1/jobs/${jobId}/shortlist`, {}, withIdempotency());
      setFlash({ kind: 'ok', msg: 'Shortlisted. Track it in Applications.' });
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (d?.error === 'already_shortlisted') setFlash({ kind: 'warn', msg: 'Already shortlisted.' });
      else setFlash({ kind: 'err', msg: 'Could not shortlist.' });
    } finally { setBusy(false); }
  };

  const hide = async () => {
    const reason = window.prompt('Why hide this job? (e.g. not_interested)') || 'not_interested';
    setBusy(true);
    try {
      await api.post(`/api/v1/jobs/${jobId}/hide`, { reason }, withIdempotency());
      nav('/feed');
    } finally { setBusy(false); }
  };

  if (error) return (
    <div className="max-w-3xl mx-auto space-y-4">
      <ErrorBlock message={error} onRetry={load} />
      <Link to="/feed" className="text-sm underline muted"><ArrowLeft className="h-3 w-3 inline" /> Back to feed</Link>
    </div>
  );
  if (!job) return <div className="max-w-3xl mx-auto"><LoadingBlock label="Loading job…" /></div>;

  const passing = job.pass_all;
  const stale = job.status === 'stale';
  const derived = job.status === 'derived' || job.needs_origin;

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fadeIn" data-testid="job-detail-page">
      <div>
        <button type="button" onClick={() => nav(-1)} className="text-xs muted underline flex items-center gap-1 mb-3"><ArrowLeft className="h-3 w-3" /> Back</button>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-2xl font-semibold">{job.title}</h1>
              {job.is_sample && <SampleBadge />}
            </div>
            <div className="muted text-sm mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="inline-flex items-center gap-1"><Building2 className="h-3.5 w-3.5" />{job.company_name}</span>
              {job.geo && <span className="inline-flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{job.geo}</span>}
              {job.comp && <span>· {job.comp}</span>}
              {job.taxonomy_family && <span className="pill pill-neutral">{job.taxonomy_family}</span>}
            </div>
            {(() => {
              const safeUrl = safeExternalHref(job.origin_url);
              return safeUrl ? (
                <a href={safeUrl} target="_blank" rel="noreferrer" className="text-xs muted underline inline-flex items-center gap-1 mt-2">
                  <ExternalLink className="h-3 w-3" /> {safeUrl}
                </a>
              ) : null;
            })()}
          </div>
          <div className="flex-shrink-0 flex items-center gap-2">
            {job.pass_all && (
              <Button
                variant="secondary"
                onClick={() => setExplainOpen(true)}
                data-testid="job-detail-why-match-btn"
              >
                <Sparkles className="h-4 w-4" /> Why this match
              </Button>
            )}
            <Button variant="ghost" onClick={hide} disabled={busy} data-testid="job-detail-hide-btn"><EyeOff className="h-4 w-4" /> Hide</Button>
            <Button variant="accent" onClick={shortlist} loading={busy} disabled={derived} data-testid="job-detail-shortlist-btn">
              <Send className="h-4 w-4" /> Shortlist
            </Button>
          </div>
        </div>

        {flash && (
          <div className={`mt-3 rounded-md px-3 py-2 text-sm border ${
            flash.kind === 'ok' ? 'border-accent/40 bg-accent/5 text-accent'
            : flash.kind === 'warn' ? 'border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400'
            : 'border-red-500/40 bg-red-500/5 text-red-700 dark:text-red-400'
          }`}>{flash.msg}</div>
        )}
      </div>

      {stale && (
        <div className="card p-4 border-amber-500/40 bg-amber-500/5">
          <div className="flex items-start gap-2"><Clock className="h-4 w-4 text-amber-600 mt-0.5" />
            <p className="text-sm">This listing hasn't been verified in the last 14 days. Confirm on the employer's site before you invest time.</p>
          </div>
        </div>
      )}

      {derived && (
        <ResolveOriginForm jobId={job.id} onResolved={load} />
      )}

      <div className="grid md:grid-cols-3 gap-4">
        <div className="md:col-span-2 space-y-4">
          <Card>
            <CardHeader title="Job description" subtitle="Verbatim from the source. We don't summarize with an LLM here." />
            <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap text-ink dark:text-ink-dark" data-testid="job-jd-text">
              {job.jd_text || <span className="muted text-sm">Employer did not include a description.</span>}
            </div>
          </Card>

          <Card>
            <CardHeader title="Have / Gap" subtitle="Based only on your APPROVED skill claims. Nothing draft is used." />
            {(job.have_gap?.required || []).length === 0 ? (
              <p className="muted text-sm">Employer didn't publish structured required skills.</p>
            ) : (
              <div className="space-y-3">
                <div>
                  <div className="text-xs muted mb-1">Have ({job.have_gap.have.length})</div>
                  <div className="flex flex-wrap gap-1">
                    {job.have_gap.have.map((s) => <span key={s} className="pill pill-accent"><CheckCircle2 className="h-3 w-3" /> {s}</span>)}
                    {job.have_gap.have.length === 0 && <span className="text-xs muted">None yet.</span>}
                  </div>
                </div>
                <div>
                  <div className="text-xs muted mb-1">Gap ({job.have_gap.gap.length})</div>
                  <div className="flex flex-wrap gap-1">
                    {job.have_gap.gap.map((s) => <span key={s} className="pill pill-neutral"><XCircle className="h-3 w-3" /> {s}</span>)}
                    {job.have_gap.gap.length === 0 && <span className="text-xs muted">Full coverage.</span>}
                  </div>
                </div>
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Route decision" subtitle="How we'd handle the application submit." />
            <p className="text-sm font-medium">{job.route?.route?.replaceAll('_', ' ')}</p>
            <p className="text-xs muted mt-1 leading-relaxed">{job.route?.rationale}</p>
          </Card>

          <Card>
            <CardHeader
              title="Gate verdict"
              subtitle={<span>
                {passing
                  ? <span className="inline-flex items-center gap-1 text-accent"><ShieldCheck className="h-3.5 w-3.5" /> All gates pass</span>
                  : <span className="inline-flex items-center gap-1 text-red-500"><ShieldOff className="h-3.5 w-3.5" /> Some gates block</span>}
                <span className="muted"> · 14 gates enumerated</span>
              </span>}
            />
            <ul>
              {(job.gates || []).map((g) => <GateRow key={g.name} g={g} />)}
            </ul>
          </Card>

          {job.reason_codes && job.reason_codes.length > 0 && (
            <Card>
              <CardHeader title="Score reason codes" subtitle="What moved the score up or down." />
              <ul className="space-y-2">
                {job.reason_codes.map((r) => (
                  <li key={r.factor} className="text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{r.factor.replaceAll('_', ' ')}</span>
                      <span className="text-xs muted">{r.direction}</span>
                    </div>
                    <p className="text-xs muted mt-0.5">{r.detail}</p>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
      {explainOpen && <MatchExplainModal jobId={job.id} onClose={() => setExplainOpen(false)} />}
    </div>
  );
}
