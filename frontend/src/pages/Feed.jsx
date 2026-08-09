import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Rss, ExternalLink, ShieldOff, AlertTriangle, Clock, MapPin, Building2,
  Send, X, ArrowRight, Ban, EyeOff, LinkIcon, TestTube2, HelpCircle,
  Briefcase, Zap, Info, DollarSign,
} from 'lucide-react';
import { api, withIdempotency } from '../lib/api';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Input from '../components/ui/Input';
import { LoadingBlock, ErrorBlock, ScopeRequiredPrompt } from '../lib/scope';
import { safeExternalHref } from '../lib/utils';
import SurpriseMeCapsule from '../components/SurpriseMeCapsule';
import ApplyWaveCapsule from '../components/ApplyWaveCapsule';

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
  // unknowns
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

function reasonLabel(code) {
  if (!code) return code;
  if (code.startsWith('missing_legal_license:')) {
    const which = code.split(':')[1] || 'license';
    return `Legally-required ${which} missing`;
  }
  return REASON_LABELS[code] || code;
}

function SampleBadge() {
  return (
    <span
      className="pill pill-neutral !bg-amber-500/10 !border-amber-500/30 !text-amber-700 dark:!text-amber-400 font-medium"
      title="Sample fixture. Excluded from every user-facing metric and cohort."
      data-testid="sample-badge"
    >
      <TestTube2 className="h-3 w-3" /> SAMPLE
    </span>
  );
}

function RouteChip({ route }) {
  const map = {
    guided_manual: { label: 'Guided manual', tone: 'accent' },
    email_application: { label: 'Email application', tone: 'accent' },
    manual_queue: { label: 'Manual queue', tone: 'neutral' },
  };
  const cfg = map[route] || { label: route, tone: 'neutral' };
  return <span className={`pill ${cfg.tone === 'accent' ? 'pill-accent' : 'pill-neutral'}`}>{cfg.label}</span>;
}

function ReasonChip({ code, tone = 'red' }) {
  const cls = tone === 'red'
    ? 'pill border-red-500/40 text-red-600 dark:text-red-400'
    : 'pill pill-neutral';
  const Icon = tone === 'red' ? AlertTriangle : HelpCircle;
  return <span className={cls}><Icon className="h-3 w-3" /> {reasonLabel(code)}</span>;
}

function scoreBadgeTone(pct) {
  if (pct >= 70) return 'bg-accent/15 text-accent border-accent/40';
  if (pct >= 45) return 'bg-neutral-100 dark:bg-neutral-800 border-line dark:border-line-dark text-ink dark:text-ink-dark';
  return 'bg-neutral-50 dark:bg-neutral-800/50 border-line dark:border-line-dark muted';
}

function ScoreBadge({ score, confidence }) {
  if (score == null) return null;
  const pct = Math.max(0, Math.min(100, Math.round(score)));
  const conf = Math.round((confidence || 0) * 100);
  const tone = scoreBadgeTone(pct);
  return (
    <div
      className={`inline-flex items-baseline gap-1 rounded-md border px-2 py-1 text-sm font-semibold ${tone}`}
      data-testid="score-badge"
      title={`Match score ${pct} · confidence ${conf}%`}
    >
      <span className="text-lg leading-none">{pct}</span>
      <span className="text-[10px] muted">/100</span>
      <span className="text-[10px] ml-1 muted">c{conf}</span>
    </div>
  );
}

function freshnessLabel(days) {
  if (days <= 0) return 'today';
  if (days === 1) return '1 day ago';
  return `${days} days ago`;
}
function freshnessTone(days) {
  if (days <= 3) return 'pill pill-accent';
  if (days > 10) return 'pill border-red-500/40 text-red-600 dark:text-red-400';
  return 'pill pill-neutral';
}

function FreshnessChip({ ts }) {
  if (!ts) return <span className="pill pill-neutral"><Clock className="h-3 w-3" /> unverified</span>;
  const d = new Date(ts);
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  return <span className={freshnessTone(days)}><Clock className="h-3 w-3" /> verified {freshnessLabel(days)}</span>;
}

function StatusChip({ status }) {
  const map = {
    live: { label: 'Live', cls: 'pill pill-accent' },
    stale: { label: 'Stale', cls: 'pill border-amber-500/40 text-amber-700 dark:text-amber-400' },
    expired: { label: 'Expired', cls: 'pill border-red-500/40 text-red-600 dark:text-red-400' },
    derived: { label: 'Needs origin', cls: 'pill pill-neutral' },
  };
  const cfg = map[status] || { label: status, cls: 'pill pill-neutral' };
  return <span className={cfg.cls}>{cfg.label}</span>;
}

// Phase 2/3 — Lane filter tabs. Career / Income Now / All.
function LaneTabs({ value, onChange }) {
  const tabs = [
    { id: 'all', label: 'All lanes', icon: Rss },
    { id: 'career', label: 'Career', icon: Briefcase, tooltip: 'Engineering / technical / knowledge work.' },
    { id: 'income_now', label: 'Income Now', icon: Zap, tooltip: 'Hourly, warehouse, driver, retail — lower barrier, faster pay.' },
  ];
  return (
    <div className="inline-flex rounded-lg border border-line dark:border-line-dark p-1 bg-white/60 dark:bg-neutral-900/60"
         role="tablist" aria-label="Job lane filter" data-testid="feed-lane-tabs">
      {tabs.map((t) => {
        const Icon = t.icon;
        const active = value === t.id;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            title={t.tooltip}
            data-testid={`feed-lane-tab-${t.id}`}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              active
                ? 'bg-accent text-white'
                : 'text-ink dark:text-ink-dark hover:bg-neutral-100 dark:hover:bg-neutral-800'
            }`}
          >
            <Icon className="h-3.5 w-3.5" /> {t.label}
          </button>
        );
      })}
    </div>
  );
}

// Phase 3 — Sort selector (best-fit / nearest / soonest money / speed).
function SortSelector({ value, onChange, lane }) {
  const opts = [
    { id: 'best_fit', label: 'Best fit' },
    { id: 'nearest', label: 'Nearest Phoenix' },
    { id: 'velocity', label: 'Soonest money' },
    // Phase 1 §iv — Speed: rank by employer median days-to-response (from
    // THIS USER's own application_outcomes). No-data employers sink last.
    { id: 'speed', label: 'Fastest to respond' },
  ];
  return (
    <div className="inline-flex items-center gap-2 text-xs muted" data-testid="feed-sort-selector">
      <span>Sort:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Sort feed"
        className="bg-transparent border border-line dark:border-line-dark rounded-md px-2 py-1 text-xs text-ink dark:text-ink-dark"
        data-testid="feed-sort-select"
      >
        {opts.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
            {lane === 'income_now' && o.id === 'velocity' ? ' (best for Income Now)' : ''}
          </option>
        ))}
      </select>
    </div>
  );
}

function LinkImportBox({ onImported }) {
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [company, setCompany] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [help, setHelp] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true); setError(null);
    try {
      const { data } = await api.post('/api/v1/jobs/import',
        { url: url.trim(), title: title.trim() || null, company_name: company.trim() || null },
        withIdempotency(),
      );
      setUrl(''); setTitle(''); setCompany('');
      onImported?.(data);
    } catch (e2) {
      const detail = e2?.response?.data?.detail;
      if (detail?.error === 'route_unavailable_platform_policy') {
        setError({
          kind: 'platform_policy',
          host: detail.host,
          message: detail.message,
        });
      } else if (detail?.error === 'invalid_url') {
        setError({ kind: 'invalid_url' });
      } else if (detail?.error === 'consent_required') {
        setError({ kind: 'consent' });
      } else {
        setError({ kind: 'unknown' });
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Paste a job you found elsewhere"
        subtitle="We import the URL, keep the employer's original posting as the source of truth, and never scrape aggregator sites."
        action={
          <button type="button" onClick={() => setHelp((h) => !h)} className="text-xs muted underline" data-testid="link-import-help-toggle">
            {help ? 'Hide help' : 'How this works'}
          </button>
        }
      />
      {help && (
        <div className="mb-4 rounded-md border border-line dark:border-line-dark p-3 text-xs muted leading-relaxed">
          <p className="mb-2 font-medium text-ink dark:text-ink-dark">Finding the employer's original posting</p>
          <ol className="list-decimal list-inside space-y-1">
            <li>Search the role title + company on Google. The employer's own careers site usually ranks in the top 3.</li>
            <li>Prefer URLs on the employer domain (e.g. <code>tesla.com/careers</code>) or their ATS (<code>boards.greenhouse.io</code>, <code>myworkdayjobs.com</code>, <code>lever.co</code>).</li>
            <li>Avoid LinkedIn / Indeed / Handshake — we never operate on aggregator sites.</li>
          </ol>
        </div>
      )}
      <form onSubmit={submit} className="space-y-3">
        <Input
          label="Employer posting URL"
          type="url"
          placeholder="https://boards.greenhouse.io/<employer>/jobs/…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          data-testid="link-import-url"
        />
        <div className="grid md:grid-cols-2 gap-3">
          <Input label="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} data-testid="link-import-title" />
          <Input label="Company (optional)" value={company} onChange={(e) => setCompany(e.target.value)} data-testid="link-import-company" />
        </div>
        {error?.kind === 'platform_policy' && (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm" data-testid="link-import-blocked">
            <div className="flex items-start gap-2">
              <Ban className="h-4 w-4 text-amber-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-medium">We don't operate on <code>{error.host}</code>.</p>
                <p className="muted mt-0.5">{error.message}</p>
                <p className="muted mt-2">Try the employer's own careers site or their ATS URL (Greenhouse, Workday, Lever, etc.).</p>
              </div>
            </div>
          </div>
        )}
        {error?.kind === 'invalid_url' && <ErrorBlock message="That doesn't look like a URL we can parse." />}
        {error?.kind === 'consent' && <ErrorBlock message="Grant discover_jobs consent to import links." />}
        {error?.kind === 'unknown' && <ErrorBlock message="Import failed. Please try again." />}
        <div className="flex items-center justify-end">
          <Button type="submit" variant="accent" loading={busy} disabled={!url.trim()} data-testid="link-import-submit">
            <LinkIcon className="h-4 w-4" /> Import posting
          </Button>
        </div>
      </form>
    </Card>
  );
}

function LaneChip({ lane }) {
  if (!lane) return null;
  const cfg = lane === 'income_now'
    ? { label: 'Income Now', cls: 'pill pill-accent', Icon: Zap }
    : { label: 'Career', cls: 'pill pill-neutral', Icon: Briefcase };
  const { Icon } = cfg;
  return <span className={cfg.cls} data-testid="job-card-lane-chip"><Icon className="h-3 w-3" /> {cfg.label}</span>;
}

function VelocityChip({ velocity }) {
  if (!velocity?.weekly_est_usd) return null;
  const w = Math.round(velocity.weekly_est_usd);
  const hourly = velocity.hourly_rate_usd ? `$${velocity.hourly_rate_usd.toFixed(2)}/hr` : null;
  return (
    <span
      className="pill pill-accent"
      title={`Est. weekly income based on posted pay${hourly ? ` (${hourly})` : ''}. Not a guarantee.`}
      data-testid="job-card-velocity-chip"
    >
      <DollarSign className="h-3 w-3" /> ~${w.toLocaleString()}/wk
    </span>
  );
}

function DistanceChip({ mi }) {
  if (typeof mi !== 'number') return null;
  const label = mi < 1 ? 'in Phoenix' : `${Math.round(mi)}mi from Phoenix`;
  return <span className="pill pill-neutral" data-testid="job-card-distance-chip"><MapPin className="h-3 w-3" /> {label}</span>;
}

// Phase 1 §iv — Speed chip. Rendered only when sort=speed and the backend
// injects a `speed` block on the card. No-data employers show a plain
// muted label so the tester can visually confirm the "no response data yet"
// state; data-bearing employers show median + response ratio.
function SpeedChip({ speed }) {
  if (!speed) return null;
  const hasData = typeof speed.median_days_to_response === 'number';
  return (
    <span
      className={`pill ${hasData ? 'pill-neutral' : 'pill-muted'}`}
      data-testid="job-card-speed-chip"
      title={speed.note || ''}
    >
      <Zap className="h-3 w-3" />
      {hasData
        ? `${speed.median_days_to_response}d median · ${speed.responded_count || 0}/${speed.sample_size || 0}`
        : 'no response data yet'}
    </span>
  );
}

function NotesList({ notes }) {
  if (!notes || notes.length === 0) return null;
  return (
    <div className="mt-2 rounded-md border border-amber-500/25 bg-amber-500/5 p-2.5 text-xs space-y-1"
         data-testid="job-card-notes">
      {notes.map((n, i) => (
        <div key={`note-${i}-${(n.note || '').slice(0, 32)}`} className="flex items-start gap-1.5">
          <Info className="h-3.5 w-3.5 mt-0.5 flex-shrink-0 text-amber-700 dark:text-amber-400" />
          <span className="text-amber-800 dark:text-amber-300 leading-snug">{n.note}</span>
        </div>
      ))}
    </div>
  );
}

// Phase 3 improvement (2026-07-27): CREDENTIAL UNLOCK PROMPT renders both on:
//   * ZERO-supply (TruthfulEmpty when passing.length === 0), and
//   * LOW-supply (LowSupplyCredentialUnlock when 0 < passing.length < 15).
// FACT RULES: unlock count = real backend query; time/cost are catalog
// ranges; each row surfaces the catalog's official `suggested_next[]` URL
// so the candidate can verify. Same live-query rails as the empty state.
const LOW_SUPPLY_THRESHOLD = 15;

function useUnlockCandidates(lane) {
  const [state, setState] = useState({ loading: true, rows: [] });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const params = new URLSearchParams();
        if (lane === 'income_now') { params.set('lane', 'income_now'); params.set('within_mi', '60'); }
        else if (lane === 'career') { params.set('lane', 'career'); }
        else { params.set('lane', 'income_now'); params.set('within_mi', '60'); }
        params.set('top_k', '3');
        const { data } = await api.get(`/api/v1/credentials/unlock-candidates?${params.toString()}`);
        if (!cancelled) setState({ loading: false, rows: data.candidates || [] });
      } catch (e) {
        if (!cancelled) setState({ loading: false, rows: [] });
      }
    })();
    return () => { cancelled = true; };
  }, [lane]);
  return state;
}

function LowSupplyCredentialUnlock({ lane, passingCount }) {
  const unlocks = useUnlockCandidates(lane);
  if (unlocks.rows.length === 0) return null;
  return (
    <div className="card p-5" data-testid="feed-low-supply-credential-unlocks">
      <p className="text-sm font-semibold text-ink dark:text-ink-dark">
        Only {passingCount} job(s) pass your gates right now — a short credential could unlock many more:
      </p>
      <p className="text-xs muted mt-1">
        Real live counts of jobs mentioning each credential within 60 miles of Phoenix. Time and cost ranges come from the linked official source.
      </p>
      <ul className="mt-3 space-y-3" data-testid="feed-low-supply-unlock-list">
        {unlocks.rows.map((row) => (
          <CredentialUnlockCard key={row.credential.id} row={row} />
        ))}
      </ul>
    </div>
  );
}

function TruthfulEmpty({ lane, totals, onSwitchLane, onGoPrefs }) {
  const unlocks = useUnlockCandidates(lane);

  const live = totals?.live_jobs || 0;
  const excludedByReason = totals?.excluded_by_reason || {};
  const topReasons = Object.entries(excludedByReason).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const laneLabel = lane === 'career' ? 'Career'
                  : lane === 'income_now' ? 'Income Now'
                  : 'this lane';
  return (
    <div className="card p-6 space-y-5" data-testid="feed-truthful-empty">
      <div className="flex items-start gap-3">
        <Info className="h-5 w-5 text-accent flex-shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink dark:text-ink-dark">
            No jobs pass every gate you've set in {laneLabel}.
          </p>
          <p className="text-sm muted mt-1 leading-relaxed">
            The feed isn't empty — <span className="font-mono">{live.toLocaleString()}</span> live job(s) are indexed{lane !== 'all' ? ' in this lane' : ''}, but your current filters exclude them all. The most common exclusions:
          </p>
          {topReasons.length > 0 && (
            <ul className="mt-2 space-y-1 text-sm" data-testid="feed-empty-top-reasons">
              {topReasons.map(([code, n]) => (
                <li key={code} className="flex items-baseline gap-2">
                  <span className="font-mono text-xs muted w-10 text-right">{n}</span>
                  <span>{reasonLabel(code)}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            {lane !== 'income_now' && (
              <Button size="sm" variant="secondary" onClick={() => onSwitchLane('income_now')} data-testid="feed-empty-try-income">
                <Zap className="h-3.5 w-3.5" /> Try Income Now lane
              </Button>
            )}
            {lane !== 'all' && (
              <Button size="sm" variant="secondary" onClick={() => onSwitchLane('all')} data-testid="feed-empty-view-all">
                <Rss className="h-3.5 w-3.5" /> View all lanes
              </Button>
            )}
            <Button size="sm" variant="accent" onClick={onGoPrefs} data-testid="feed-empty-widen-prefs">
              Widen my preferences <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </div>
          <p className="text-xs muted mt-3 leading-relaxed">
            Tip: location and remote-only preferences are the most common cause. If you're open to remote roles or a wider commute radius, updating preferences usually unlocks 100s of live jobs.
          </p>
        </div>
      </div>

      {unlocks.rows.length > 0 && (
        <div className="border-t border-line dark:border-line-dark pt-4" data-testid="feed-empty-credential-unlocks">
          <p className="text-sm font-semibold text-ink dark:text-ink-dark">
            Or — unlock more Income Now jobs with a short credential:
          </p>
          <p className="text-xs muted mt-1">
            Real live counts of jobs mentioning each credential within 60 miles of Phoenix. Time and cost ranges come from the linked official source.
          </p>
          <ul className="mt-3 space-y-3" data-testid="feed-empty-unlock-list">
            {unlocks.rows.map((row) => (
              <CredentialUnlockCard key={row.credential.id} row={row} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function CredentialUnlockCard({ row }) {  const c = row.credential;
  const wl = c.time_to_credential.weeks_low;
  const wh = c.time_to_credential.weeks_high;
  const cl = c.approx_cost_usd.low;
  const ch = c.approx_cost_usd.high;
  const suggested = (c.suggested_next && c.suggested_next[0]) || null;
  return (
    <li className="rounded-md border border-line dark:border-line-dark p-3" data-testid={`credential-unlock-${c.id}`}>
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="font-mono text-sm text-accent" data-testid={`credential-unlock-count-${c.id}`}>
          +{row.live_unlock_count} jobs
        </span>
        <span className="text-sm font-semibold text-ink dark:text-ink-dark">{c.label}</span>
        {c.mandatory && <span className="pill pill-neutral text-[10px]">statutory</span>}
      </div>
      <div className="text-xs muted mt-1">
        Typical time: <span className="text-ink dark:text-ink-dark font-mono">{wl}–{wh} wks</span>
        {' · '}Typical cost: <span className="text-ink dark:text-ink-dark font-mono">${cl.toLocaleString()}–${ch.toLocaleString()}</span>
      </div>
      {row.sample_titles && row.sample_titles.length > 0 && (
        <div className="text-xs muted mt-1 truncate">
          e.g. {row.sample_titles.slice(0, 2).join(' · ')}
        </div>
      )}
      {suggested && (
        <a href={suggested.url} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 text-xs text-accent hover:underline mt-2"
           data-testid={`credential-unlock-link-${c.id}`}>
          Verify at {suggested.label} <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </li>
  );
}

function JobCard({ job, onShortlist, onHide, onExplain, busy }) {
  return (
    <div className="card p-5 space-y-3" data-testid={`job-card-${job.id}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Link to={`/jobs/${job.id}`} className="text-base font-semibold text-ink dark:text-ink-dark hover:underline" data-testid={`job-title-link-${job.id}`}>
              {job.title}
            </Link>
            {job.is_sample && <SampleBadge />}
            <StatusChip status={job.status} />
            <LaneChip lane={job.lane} />
          </div>
          <div className="text-sm muted mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="inline-flex items-center gap-1"><Building2 className="h-3 w-3" />{job.company_name}</span>
            {job.geo && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{job.geo}</span>}
            {job.comp && <span>· {job.comp}</span>}
          </div>
        </div>
        <ScoreBadge score={job.score} confidence={job.confidence} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <RouteChip route={job.route?.route} />
        <FreshnessChip ts={job.last_verified} />
        <DistanceChip mi={job.distance_from_phoenix_mi} />
        <VelocityChip velocity={job.velocity} />
        <SpeedChip speed={job.speed} />
        {job.taxonomy_family && <span className="pill pill-neutral">{job.taxonomy_family}</span>}
        {(job.top_reasons || []).slice(0, 3).map((r) => (
          <span key={r.factor} className={`pill ${r.direction === 'positive' ? 'pill-accent' : 'pill-neutral'}`}>
            {r.direction === 'positive' ? '+' : '·'} {r.factor.replaceAll('_', ' ')}
          </span>
        ))}
      </div>

      <NotesList notes={job.notes} />

      <div className="flex items-center justify-between pt-1">
        <button type="button" onClick={() => onExplain(job)} className="text-xs muted underline" data-testid={`job-explain-btn-${job.id}`}>
          Why this score?
        </button>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => onHide(job)} disabled={busy}>
            <EyeOff className="h-3 w-3" /> Hide
          </Button>
          <Button size="sm" variant="accent" onClick={() => onShortlist(job)} loading={busy} data-testid={`job-shortlist-btn-${job.id}`}>
            <Send className="h-3 w-3" /> Shortlist
          </Button>
        </div>
      </div>
    </div>
  );
}

function ExcludedCard({ job }) {
  return (
    <div className="rounded-card border border-line dark:border-line-dark p-4 bg-white/60 dark:bg-neutral-900/60" data-testid={`excluded-card-${job.id}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Link to={`/jobs/${job.id}`} className="text-sm font-medium text-ink dark:text-ink-dark hover:underline">
              {job.title}
            </Link>
            {job.is_sample && <SampleBadge />}
          </div>
          <div className="text-xs muted mt-0.5">{job.company_name}</div>
        </div>
      </div>
      <div className="flex flex-wrap gap-1 mt-2">
        {(job.fail_reasons || []).map((r) => <ReasonChip key={r} code={r} tone="red" />)}
        {(job.unknown_reasons || []).map((r) => <ReasonChip key={r} code={r} tone="neutral" />)}
      </div>
    </div>
  );
}

function counterfactualFrom(reasonCodes) {
  // Founder Fix Round-2 · P0 #3 — one concrete counterfactual line, derived from a REAL
  // UNKNOWN or gap factor. No fabrication: if no UNKNOWN/gap exists we return null and the
  // modal omits the section.
  if (!Array.isArray(reasonCodes) || reasonCodes.length === 0) return null;
  const unknown = reasonCodes.find((r) => r.direction === 'unknown' || (r.value == null && r.weight_applied === 0));
  if (unknown) {
    return {
      kind: 'unknown',
      factor: unknown.factor,
      text: `If you resolved ${unknown.factor.replaceAll('_', ' ')}, up to ${unknown.weight_ideal || '—'} points of score weight would count toward your total instead of being renormalized out.`,
    };
  }
  // Otherwise pick the lowest-value factor that still had weight applied.
  const applied = reasonCodes.filter((r) => (r.weight_applied || 0) > 0 && r.value != null);
  if (applied.length === 0) return null;
  applied.sort((a, b) => (a.value ?? 1) - (b.value ?? 1));
  const worst = applied[0];
  if ((worst.value ?? 1) >= 0.9) return null; // no meaningful gap
  return {
    kind: 'gap',
    factor: worst.factor,
    text: `Your weakest signal here is ${worst.factor.replaceAll('_', ' ')} at ${Math.round((worst.value || 0) * 100)}%. Closing that gap would move the score up by roughly ${Math.round(((1 - (worst.value || 0)) * (worst.weight_applied || 0)))} points.`,
  };
}

function MatchExplainModal({ jobId, onClose }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fbSent, setFbSent] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [{ data: score }, { data: job }] = await Promise.all([
          api.get(`/api/v1/matches/for-job/${jobId}`),
          api.get(`/api/v1/jobs/${jobId}`),
        ]);
        if (alive) {
          setData({ score, job });
          // Reflect prior feedback if the API surfaced it (P1 #4).
          if (score?.feedback && typeof score.feedback.helpful === 'boolean') {
            setFbSent(score.feedback.helpful);
          }
        }
      } catch {
        if (alive) setError('Could not load explanation.');
      }
    })();
    return () => { alive = false; };
  }, [jobId]);

  const sendFeedback = async (helpful) => {
    setBusy(true);
    try {
      await api.post(`/api/v1/matches/for-job/${jobId}/feedback`, { helpful }, withIdempotency());
      setFbSent(helpful);
    } finally { setBusy(false); }
  };

  const topFactors = (data?.score?.reason_codes || []).slice(0, 5);
  const counterfactual = counterfactualFrom(data?.score?.reason_codes);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4 animate-fadeIn" onClick={onClose}>
      <div className="card max-w-2xl w-full p-6 max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="match-explain-modal">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h3 className="text-base font-semibold" data-testid="match-modal-title">Why this match</h3>
            <p className="text-xs muted mt-0.5">
              Score is a weighted composite. UNKNOWN factors are renormalized out honestly — they never inflate confidence.
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn btn-ghost !p-1.5" aria-label="Close" data-testid="match-explain-close"><X className="h-4 w-4" /></button>
        </div>
        {!data && !error && <LoadingBlock />}
        {error && <ErrorBlock message={error} onRetry={onClose} />}
        {data && (
          <>
            <div className="flex items-center gap-4 pb-4 border-b border-line dark:border-line-dark">
              <ScoreBadge score={data.score.score} confidence={data.score.confidence} />
              <div className="text-xs muted">weights_version <span className="font-mono">{data.score.weights_version}</span> · used weight {Math.round((data.score.confidence || 0) * 100)}%</div>
            </div>

            <div className="mt-4">
              <div className="text-xs muted mb-2">Top 5 factors driving this score</div>
              <div className="space-y-3" data-testid="match-modal-factor-bars">
                {topFactors.map((r) => (
                  <FactorRow key={r.factor} r={r} />
                ))}
              </div>
            </div>

            {counterfactual && (
              <div
                className="mt-5 rounded-md border border-accent/30 bg-accent/5 p-3 text-sm"
                data-testid="match-modal-counterfactual"
              >
                <div className="text-xs uppercase tracking-wide muted mb-1">Counterfactual</div>
                {counterfactual.text}
              </div>
            )}

            <div className="mt-6 pt-4 border-t border-line dark:border-line-dark">
              <p className="text-xs muted mb-2">
                {fbSent === null ? 'Was this explanation useful?' : 'Your feedback is recorded — click again to change.'}
              </p>
              <div className="flex items-center gap-2">
                <Button size="sm" variant={fbSent === true ? 'accent' : 'secondary'} onClick={() => sendFeedback(true)} loading={busy && fbSent !== false} data-testid="match-feedback-helpful">Yes</Button>
                <Button size="sm" variant={fbSent === false ? 'accent' : 'secondary'} onClick={() => sendFeedback(false)} loading={busy && fbSent !== true} data-testid="match-feedback-unhelpful">Not really</Button>
                {fbSent !== null && <span className="text-xs muted ml-2">Thanks — recorded.</span>}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export { MatchExplainModal };

function FactorRow({ r }) {
  const pct = r.value == null ? null : Math.max(0, Math.min(1, r.value)) * 100;
  const isUnknown = r.direction === 'unknown' || r.value == null || r.weight_applied === 0;
  const barCls = isUnknown ? 'bg-neutral-300 dark:bg-neutral-700'
    : r.direction === 'positive' ? 'bg-accent' : 'bg-red-500/70';
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{r.factor.replaceAll('_', ' ')}</span>
        <span className="text-xs muted">
          {isUnknown ? 'UNKNOWN' : `${Math.round(pct)}%`}
          {r.weight_applied ? ` · weight ${r.weight_applied}` : ' · weight renormalized out'}
        </span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-neutral-100 dark:bg-neutral-800 overflow-hidden">
        <div className={`h-full ${barCls}`} style={{ width: isUnknown ? '18%' : `${pct}%`, opacity: isUnknown ? 0.6 : 1 }} />
      </div>
      <p className="text-xs muted mt-1">{r.detail}</p>
    </div>
  );
}

export default function FeedPage() {
  const [state, setState] = useState({ loading: true, error: null, data: null, needsScope: false, passportBlocked: false });
  const [busy, setBusy] = useState(null);
  const [explainJobId, setExplainJobId] = useState(null);
  const [imports, setImports] = useState([]);
  const [flash, setFlash] = useState(null);
  const [lane, setLane] = useState('all');
  const [sort, setSort] = useState('best_fit');
  const nav = useNavigate();

  const load = useCallback(async (laneArg, sortArg) => {
    const _lane = laneArg ?? lane;
    const _sort = sortArg ?? sort;
    setState((s) => ({ ...s, loading: true, error: null, needsScope: false, passportBlocked: false }));
    try {
      const qs = new URLSearchParams();
      if (_lane && _lane !== 'all') qs.set('lane', _lane);
      if (_sort && _sort !== 'best_fit') qs.set('sort', _sort);
      const suffix = qs.toString() ? `?${qs.toString()}` : '';
      const { data } = await api.get(`/api/v1/jobs/feed${suffix}`);
      setState({ loading: false, error: null, data, needsScope: false, passportBlocked: false });
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') {
        setState({ loading: false, error: null, data: null, needsScope: true, passportBlocked: false });
      } else if (detail?.error === 'passport_not_activated') {
        setState({ loading: false, error: null, data: null, needsScope: false, passportBlocked: true });
      } else {
        setState({ loading: false, error: 'Could not load your feed.', data: null, needsScope: false, passportBlocked: false });
      }
    }
  }, [lane, sort]);

  const loadImports = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/jobs/imports/me');
      setImports(data.imports || []);
    } catch (e) { console.debug('imports load skipped (likely consent gate)', e); }
  }, []);

  useEffect(() => { load(); loadImports(); }, [load, loadImports]);

  const onLaneChange = (id) => {
    setLane(id);
    // Auto-suggest velocity sort when switching to Income Now for the first time.
    if (id === 'income_now' && sort === 'best_fit') {
      setSort('velocity');
      load(id, 'velocity');
    } else {
      load(id, sort);
    }
  };

  const onSortChange = (s) => {
    setSort(s);
    load(lane, s);
  };

  const passing = useMemo(() => state.data?.passing || [], [state.data]);
  const excluded = useMemo(() => state.data?.excluded || [], [state.data]);
  const totals = state.data?.totals || {};

  // SAMPLE-safe metric: exclude sample rows from user-facing count of "opportunities passing"
  const passingReal = useMemo(() => passing.filter((j) => !j.is_sample), [passing]);
  const passingSample = passing.length - passingReal.length;

  const shortlist = async (job) => {
    setBusy(job.id);
    try {
      await api.post(`/api/v1/jobs/${job.id}/shortlist`, {}, withIdempotency());
      setFlash({ kind: 'ok', msg: `Shortlisted "${job.title}". Track it in Applications.` });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (d?.error === 'already_shortlisted') setFlash({ kind: 'warn', msg: 'You already have an open application for this job.' });
      else if (d?.error === 'employer_cap_reached') setFlash({ kind: 'warn', msg: d.message || `Rolling ${d.cap}-per-${d.window_days}-day cap reached for ${d.employer || 'this employer'}.` });
      else setFlash({ kind: 'err', msg: 'Could not shortlist.' });
    } finally { setBusy(null); }
  };

  const hide = async (job) => {
    const reason = window.prompt('Why hide this job? (e.g., not_interested, location, comp)') || 'not_interested';
    setBusy(job.id);
    try {
      await api.post(`/api/v1/jobs/${job.id}/hide`, { reason }, withIdempotency());
      await load();
    } finally { setBusy(null); }
  };

  if (state.needsScope) {
    return (
      <div className="max-w-4xl mx-auto space-y-6">
        <h1 className="text-2xl font-semibold flex items-center gap-2"><Rss className="h-5 w-5" /> Opportunity feed</h1>
        <ScopeRequiredPrompt scope="discover_jobs" description="The feed shows live jobs your Passport passes eligibility for, scored honestly. It only runs after you grant discover_jobs." onGranted={load} />
      </div>
    );
  }

  if (state.passportBlocked) {
    return (
      <div className="max-w-4xl mx-auto space-y-6">
        <h1 className="text-2xl font-semibold flex items-center gap-2"><Rss className="h-5 w-5" /> Opportunity feed</h1>
        <div className="card p-6" data-testid="passport-not-activated">
          <div className="flex items-start gap-3">
            <ShieldOff className="h-5 w-5 text-accent" />
            <div>
              <p className="text-sm font-semibold">Activate your Passport first</p>
              <p className="text-sm muted mt-1 max-w-lg leading-relaxed">
                The feed only turns on when your Passport is activated — we don't want you browsing jobs
                against unverified claims. Head to Passport, approve at least one identity claim plus one
                education or employment claim, then hit Activate.
              </p>
              <Button variant="accent" className="mt-3" onClick={() => nav('/passport')} data-testid="go-passport-btn">Go to Passport <ArrowRight className="h-4 w-4" /></Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6 animate-fadeIn" data-testid="feed-page">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2"><Rss className="h-5 w-5" /> Opportunity feed</h1>
          <p className="muted text-sm mt-1 max-w-2xl">Live jobs your Passport passes eligibility for. Excluded jobs are shown too — with reasons — because that intelligence is the product.</p>
        </div>
        <div className="text-xs muted">
          weights_version <span className="font-mono">{state.data?.weights_version || '—'}</span>
        </div>
      </div>

      {flash && (
        <div className={`rounded-md px-3 py-2 text-sm border ${
          flash.kind === 'ok' ? 'border-accent/40 bg-accent/5 text-accent'
          : flash.kind === 'warn' ? 'border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400'
          : 'border-red-500/40 bg-red-500/5 text-red-700 dark:text-red-400'
        }`}>
          {flash.msg}
          <button type="button" onClick={() => setFlash(null)} className="ml-3 text-xs underline">dismiss</button>
        </div>
      )}

      <div className="grid md:grid-cols-3 gap-4">
        <div className="liquid-card p-5">
          <div className="text-xs muted">Opportunities passing all gates</div>
          <div className="text-3xl font-semibold mt-1 tracking-display" data-testid="feed-totals-passing-real">{passingReal.length}</div>
          <div className="text-[11px] muted mt-1">Excludes {passingSample} SAMPLE row(s) from the count — they're shown, not measured.</div>
        </div>
        <div className="liquid-card p-5">
          <div className="text-xs muted">Excluded (with reasons)</div>
          <div className="text-3xl font-semibold mt-1 tracking-display" data-testid="feed-totals-excluded">{excluded.length}</div>
          <div className="text-[11px] muted mt-1">Includes SAMPLE rows — badged, never counted in production cohorts.</div>
        </div>
        <div className="liquid-card p-5">
          <div className="text-xs muted">Live jobs in this lane</div>
          <div className="text-3xl font-semibold mt-1 tracking-display" data-testid="feed-totals-live-in-lane">{totals.live_jobs ?? ((totals.passing || 0) + (totals.excluded || 0))}</div>
          <div className="text-[11px] muted mt-1">Feed is fresh-only. Anything older than 14 days is auto-marked stale.</div>
        </div>
      </div>

      {/* Fynd Liquid — Surprise Me draw (outside your usual lanes) */}
      <SurpriseMeCapsule />

      {/* Phase 2/3 — Lane filter + sort selector */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <LaneTabs value={lane} onChange={onLaneChange} />
        <SortSelector value={sort} onChange={onSortChange} lane={lane} />
      </div>

      {/* Phase 1 §v — Apply Wave (batch authorize with cap-respecting preview) */}
      <ApplyWaveCapsule lane={lane} withinMi={null} onWaved={() => load()} />

      {state.loading && <LoadingBlock label="Scoring your feed…" />}
      {state.error && <ErrorBlock message={state.error} onRetry={load} />}

      {!state.loading && !state.error && (
        <>
          <section>
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-lg font-semibold">Passing your gates ({passing.length})</h2>
              <span className="text-xs muted">
                {sort === 'nearest' ? 'Sorted by proximity to Phoenix'
                  : sort === 'velocity' ? 'Sorted by soonest expected weekly income'
                  : sort === 'speed' ? 'Sorted by fastest employer response · no-data last'
                  : 'Sorted by score'}
              </span>
            </div>
            {passing.length === 0 ? (
              <TruthfulEmpty
                lane={lane}
                totals={totals}
                onSwitchLane={onLaneChange}
                onGoPrefs={() => nav('/preferences')}
              />
            ) : (
              <>
                <div className="grid md:grid-cols-2 gap-3">
                  {passing.map((j) => (
                    <JobCard
                      key={j.id}
                      job={j}
                      busy={busy === j.id}
                      onShortlist={shortlist}
                      onHide={hide}
                      onExplain={(job) => setExplainJobId(job.id)}
                    />
                  ))}
                </div>
                {passing.length < LOW_SUPPLY_THRESHOLD && (
                  <div className="mt-4">
                    <LowSupplyCredentialUnlock lane={lane} passingCount={passing.length} />
                  </div>
                )}
              </>
            )}
          </section>

          <section>
            <h2 className="text-lg font-semibold mb-3">Excluded — the intelligence layer ({excluded.length})</h2>
            <div className="grid md:grid-cols-2 gap-2">
              {excluded.map((j) => <ExcludedCard key={j.id} job={j} />)}
            </div>
          </section>
        </>
      )}

      <section className="pt-4 border-t border-line dark:border-line-dark">
        <h2 className="text-lg font-semibold mb-3 flex items-center gap-2"><LinkIcon className="h-4 w-4" /> Manual import</h2>
        <p className="muted text-sm mb-3 max-w-2xl">Found something not in our feed? Paste the employer's original posting. We don't operate on LinkedIn, Indeed, or Handshake — please find the original URL.</p>
        <LinkImportBox onImported={loadImports} />
        {imports.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-semibold mb-2">Your imports ({imports.length})</h3>
            <ul className="divide-y divide-line dark:divide-line-dark" data-testid="imports-list">
              {imports.map((i) => (
                <li key={i.id} className="py-3 flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <Link to={`/jobs/${i.id}`} className="text-sm text-ink dark:text-ink-dark hover:underline">{i.title}</Link>
                    <div className="text-xs muted flex items-center gap-1 mt-0.5">
                      <ExternalLink className="h-3 w-3" />
                      {(() => { const safeUrl = safeExternalHref(i.origin_url); return safeUrl ? (
                        <a href={safeUrl} target="_blank" rel="noreferrer" className="hover:underline truncate">{safeUrl}</a>
                      ) : (
                        <span className="truncate text-neutral-400" title="URL blocked (unsafe scheme)">{i.origin_url}</span>
                      ); })()}
                    </div>
                    {i.needs_origin && i.resolver_label && (
                      <p
                        className="text-xs text-amber-700 dark:text-amber-400 mt-1 leading-relaxed"
                        data-testid={`imports-resolver-label-${i.id}`}
                      >
                        {i.resolver_label}
                      </p>
                    )}
                  </div>
                  <StatusChip status={i.status} />
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {explainJobId && <MatchExplainModal jobId={explainJobId} onClose={() => setExplainJobId(null)} />}
    </div>
  );
}
