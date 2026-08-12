import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Rocket,
  ShieldCheck,
  Fingerprint,
  Radar,
  Wallet,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Radio,
} from 'lucide-react';
import { api, withIdempotency } from '../lib/api';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Input from '../components/ui/Input';
import { LoadingBlock, ErrorBlock } from '../lib/scope';

/**
 * Phase 6 Batch D — /onboarding/launch  "Two-Tap Onboarding" screen.
 *
 * Composes into ONE screen the four post-upload user actions:
 *   1. Bulk-attest the Passport claim set (SHA-256 pinned).
 *   2. Confirm / edit the auto-suggested spectrum (titles / radius / pay floor).
 *   3. Preview the initial Apply-Wave.
 *   4. Verbatim per-scope consent + single "Authorize & Launch" tap.
 *
 * Rails:
 * - Consent language is rendered VERBATIM per scope from `/api/v1/meta/policy`
 *   (label + description). No collapsing / summarising / paraphrasing.
 * - Spectrum step surfaces the honest `pay_floor: null` state when the
 *   Passport has no verified compensation history — never fabricates a
 *   number.
 * - Zero-credit users see the HTTP 402 `paused_no_credits` state
 *   inline BEFORE tapping Authorize (auto-apply would halt at first
 *   dispatch; the UI honestly shows that).
 * - Full state coverage: loading · error · empty-eligibles · paused_no_credits
 *   · success. Every interactive element carries a data-testid.
 */

const LAUNCH_SCOPES = ['submit_applications', 'process_career_data'];

const DEFAULT_SPECTRUM = {
  titles: [],
  radius_mi: 25,
  pay_floor: null,
  rationale: {},
  honest_label: '',
};

const DEFAULT_WAVE_CAP = 25;

function formatPayFloor(n) {
  if (n == null) return null;
  return `$${Number(n).toLocaleString()}`;
}

function StepBadge({ n, title, subtitle, icon: Icon }) {
  return (
    <div className="flex items-start gap-3">
      <div className="h-9 w-9 shrink-0 rounded-full border border-line dark:border-line-dark grid place-items-center text-xs font-semibold">
        {Icon ? <Icon className="h-4 w-4" /> : n}
      </div>
      <div className="min-w-0">
        <h3 className="text-base font-semibold leading-tight">{title}</h3>
        {subtitle && <p className="text-sm muted mt-0.5">{subtitle}</p>}
      </div>
    </div>
  );
}

function AttestSummary({ claims, loading }) {
  if (loading) return <LoadingBlock label="Reading Passport…" />;
  const groups = claims?.groups || [];
  const byType = groups.map((g) => ({ type: g.type, count: g.claims?.length || 0 }));
  const total = byType.reduce((s, x) => s + x.count, 0);
  const approved = groups.reduce(
    (s, g) => s + (g.claims || []).filter((c) => c.status === 'approved').length,
    0,
  );
  const pending = total - approved;

  if (total === 0) {
    return (
      <div
        className="rounded-md border border-dashed border-line dark:border-line-dark p-4 text-sm muted"
        data-testid="launch-attest-empty"
      >
        No claims in your Passport yet. Upload a résumé or add claims manually
        from the Passport screen before launching.
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="launch-attest-summary">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
        <span>
          <span className="font-semibold" data-testid="launch-attest-total">{total}</span>{' '}
          claims in Passport
        </span>
        <span className="muted">•</span>
        <span>
          <span className="font-semibold" data-testid="launch-attest-approved">{approved}</span>{' '}
          already approved
        </span>
        {pending > 0 && (
          <>
            <span className="muted">•</span>
            <span className="text-amber-600 dark:text-amber-400">
              <span className="font-semibold" data-testid="launch-attest-pending">{pending}</span>{' '}
              pending — this launch will attest them
            </span>
          </>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5" data-testid="launch-attest-type-chips">
        {byType.map((row) => (
          <span key={row.type} className="pill pill-muted text-[11px]">
            {row.type} · {row.count}
          </span>
        ))}
      </div>
      <p className="text-[11px] muted">
        Authorize hashes this exact set (SHA-256) and stores the hash on your
        consent ledger — the attestation is cryptographically pinned.
      </p>
    </div>
  );
}

function SpectrumStep({ spectrum, editable, onChange }) {
  const payLabel = formatPayFloor(spectrum.pay_floor);
  const titles = spectrum.titles || [];

  const addTitle = (v) => {
    const t = v.trim();
    if (!t) return;
    if (titles.includes(t)) return;
    onChange({ titles: [...titles, t] });
  };
  const removeTitle = (t) => onChange({ titles: titles.filter((x) => x !== t) });

  const [titleDraft, setTitleDraft] = useState('');

  return (
    <div className="space-y-3" data-testid="launch-spectrum">
      {spectrum.honest_label && (
        <p className="text-[11px] muted" data-testid="launch-spectrum-honest-label">
          {spectrum.honest_label}
        </p>
      )}

      {/* Titles */}
      <div>
        <label className="field-label" htmlFor="launch-spectrum-title-input">Target titles</label>
        {titles.length === 0 ? (
          <div className="text-xs muted mt-1" data-testid="launch-spectrum-titles-empty">
            {spectrum.rationale?.titles_source === 'no_approved_role_or_experience_claims'
              ? 'No approved role or experience claims yet — add one to auto-suggest a title.'
              : 'No titles suggested. Add one manually below.'}
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5 mt-1" data-testid="launch-spectrum-titles-chips">
            {titles.map((t) => (
              <span key={t} className="pill pill-accent text-xs">
                {t}
                {editable && (
                  <button
                    type="button"
                    onClick={() => removeTitle(t)}
                    className="ml-1 opacity-70 hover:opacity-100"
                    aria-label={`Remove ${t}`}
                    data-testid={`launch-spectrum-remove-title-${t}`}
                  >
                    ×
                  </button>
                )}
              </span>
            ))}
          </div>
        )}
        {editable && (
          <div className="flex items-center gap-2 mt-2 max-w-md">
            <Input
              id="launch-spectrum-title-input"
              type="text"
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addTitle(titleDraft);
                  setTitleDraft('');
                }
              }}
              placeholder="Add a title (press Enter)"
              data-testid="launch-spectrum-title-input"
            />
            <Button
              size="sm"
              variant="secondary"
              onClick={() => { addTitle(titleDraft); setTitleDraft(''); }}
              data-testid="launch-spectrum-add-title"
            >
              Add
            </Button>
          </div>
        )}
      </div>

      {/* Radius */}
      <div>
        <label className="field-label" htmlFor="launch-spectrum-radius">Radius (miles)</label>
        <div className="flex items-center gap-3 max-w-xs">
          <Input
            id="launch-spectrum-radius"
            type="number"
            min={0}
            max={500}
            value={spectrum.radius_mi ?? 25}
            onChange={(e) => onChange({ radius_mi: e.target.value === '' ? 25 : Number(e.target.value) })}
            data-testid="launch-spectrum-radius-input"
          />
        </div>
        <p className="text-[11px] muted mt-1">
          {spectrum.rationale?.radius_source || 'default (25 mi) — edit anytime'}
        </p>
      </div>

      {/* Pay floor — HONEST null state */}
      <div>
        <label className="field-label" htmlFor="launch-spectrum-pay-floor">Pay floor (USD)</label>
        {payLabel ? (
          <>
            <div className="flex items-center gap-3 max-w-xs">
              <Input
                id="launch-spectrum-pay-floor"
                type="number"
                min={0}
                step={5000}
                value={spectrum.pay_floor ?? ''}
                onChange={(e) => onChange({
                  pay_floor: e.target.value === '' ? null : Number(e.target.value),
                })}
                data-testid="launch-spectrum-pay-floor-input"
              />
              <span
                className="text-xs font-medium"
                data-testid="launch-spectrum-pay-floor-display"
              >
                {payLabel}
              </span>
            </div>
            <p className="text-[11px] muted mt-1" data-testid="launch-spectrum-pay-floor-rationale">
              {spectrum.rationale?.pay_floor}
            </p>
          </>
        ) : (
          <div
            className="rounded-md border border-dashed border-line dark:border-line-dark px-3 py-2 max-w-md"
            data-testid="launch-spectrum-pay-floor-empty"
          >
            <div className="text-xs">
              No verified pay history yet — pay floor left blank.
            </div>
            <p className="text-[11px] muted mt-1">
              We only surface a floor when your Passport has verified compensation-history claims.
              Set one manually below to filter your feed.
            </p>
            <div className="mt-2">
              <Input
                type="number"
                min={0}
                step={5000}
                value={spectrum.pay_floor ?? ''}
                placeholder="Optional — leave blank for no floor"
                onChange={(e) => onChange({
                  pay_floor: e.target.value === '' ? null : Number(e.target.value),
                })}
                data-testid="launch-spectrum-pay-floor-manual-input"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function WavePreviewStep({ preview, loading, error, onRefresh }) {
  if (loading) return <LoadingBlock label="Previewing wave…" />;
  if (error) {
    return (
      <ErrorBlock message={error} onRetry={onRefresh} />
    );
  }
  if (!preview) return null;

  const eligibleCount = preview.eligible_count || 0;
  const breakdown = preview.breakdown || {};
  const items = preview.eligible_summary || [];

  if (eligibleCount === 0) {
    return (
      <div
        className="rounded-md border border-dashed border-line dark:border-line-dark p-4"
        data-testid="launch-wave-empty"
      >
        <div className="text-sm">
          No jobs match your spectrum right now.
        </div>
        <p className="text-xs muted mt-1">
          Scanned {breakdown.total_scanned ?? 0} live postings ·
          scope-blocked {breakdown.blocked_scope ?? 0} ·
          gate-blocked {breakdown.blocked_hard_gate ?? 0} ·
          cap-blocked {breakdown.blocked_cap ?? 0} ·
          duplicates {breakdown.blocked_duplicate ?? 0}.
        </p>
        <p className="text-xs muted mt-2">
          You can still authorize — Standing Wave will queue matches as they arrive.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="launch-wave-preview">
      <div className="text-sm">
        Would queue{' '}
        <span className="font-semibold" data-testid="launch-wave-eligible-count">
          {eligibleCount}
        </span>{' '}
        job{eligibleCount === 1 ? '' : 's'} of {breakdown.total_scanned ?? 0} scanned.
      </div>
      <div className="text-[11px] muted grid grid-cols-2 gap-x-4 gap-y-0.5">
        <div>scope-blocked <span data-testid="launch-wave-scope-blocked">{breakdown.blocked_scope ?? 0}</span></div>
        <div>gate-blocked <span data-testid="launch-wave-gate-blocked">{breakdown.blocked_hard_gate ?? 0}</span></div>
        <div>cap-blocked <span data-testid="launch-wave-cap-blocked">{breakdown.blocked_cap ?? 0}</span></div>
        <div>duplicates <span data-testid="launch-wave-dupe-blocked">{breakdown.blocked_duplicate ?? 0}</span></div>
      </div>
      <div className="max-h-40 overflow-y-auto space-y-1" data-testid="launch-wave-eligible-list">
        {items.slice(0, 12).map((j) => (
          <div key={j.id} className="text-[11px] flex items-center gap-2">
            <span className="text-teal-500">•</span>
            <span className="font-medium truncate">{j.title || '(untitled)'}</span>
            <span className="muted truncate">{j.company_name || ''}</span>
          </div>
        ))}
        {items.length > 12 && (
          <div className="text-[11px] muted">+ {items.length - 12} more</div>
        )}
      </div>
    </div>
  );
}

function CreditsBanner({ credits }) {
  if (!credits) return null;
  const { balance, plan, is_unlimited } = credits;
  if (is_unlimited) {
    return (
      <div
        className="rounded-md border border-teal-500/30 bg-teal-500/5 px-3 py-2 text-xs flex items-center gap-2"
        data-testid="launch-credits-unlimited"
      >
        <Wallet className="h-3.5 w-3.5 text-teal-500" />
        Unlimited plan — application dispatch never halts on credits.
      </div>
    );
  }
  if ((balance ?? 0) <= 0) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/5 p-3 text-xs space-y-1"
        data-testid="launch-credits-paused-no-credits"
      >
        <div className="flex items-center gap-2 font-semibold text-red-700 dark:text-red-300">
          <AlertTriangle className="h-3.5 w-3.5" />
          <span>0 credits — auto-apply will pause (HTTP 402 · paused_no_credits)</span>
        </div>
        <div className="muted">
          You can still queue the wave (shortlist rows are safe). Each dispatch
          debits 1 credit; with 0 balance, the first send returns HTTP 402 and
          the item stays parked. Refills land automatically on UTC month-start;
          an admin can also grant credits.
        </div>
      </div>
    );
  }
  return (
    <div
      className="rounded-md border border-line dark:border-line-dark px-3 py-2 text-xs flex items-center gap-2"
      data-testid="launch-credits-ok"
    >
      <Wallet className="h-3.5 w-3.5" />
      <span>
        <span className="font-semibold" data-testid="launch-credits-balance">{balance}</span>{' '}
        credits · plan <span className="font-mono">{plan}</span>
      </span>
    </div>
  );
}

function ConsentStep({ scopes, checked, onToggle, policyVersion }) {
  return (
    <div className="space-y-2" data-testid="launch-consent-scopes">
      {LAUNCH_SCOPES.map((key) => {
        const s = scopes?.find((x) => x.scope === key);
        if (!s) return null;
        const on = checked.includes(key);
        return (
          <label
            key={key}
            className={`flex items-start gap-3 rounded-md border p-3 text-sm cursor-pointer transition-colors ${on ? 'border-accent bg-accent/5' : 'border-line dark:border-line-dark'}`}
            data-testid={`launch-consent-row-${key}`}
          >
            <input
              type="checkbox"
              checked={on}
              onChange={() => onToggle(key)}
              className="h-4 w-4 mt-0.5 rounded border-line dark:border-line-dark accent-emerald-700"
              data-testid={`launch-consent-toggle-${key}`}
            />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <div className="font-medium" data-testid={`launch-consent-label-${key}`}>{s.label}</div>
                <code className="text-[10px] muted font-mono">{s.scope}</code>
                {s.required && <span className="text-[10px] uppercase tracking-wider text-amber-600 dark:text-amber-400">required</span>}
              </div>
              <p className="text-xs muted mt-1" data-testid={`launch-consent-description-${key}`}>
                {s.description}
              </p>
            </div>
          </label>
        );
      })}
      <p className="text-[11px] muted">
        Consenting to policy version{' '}
        <code className="font-mono" data-testid="launch-consent-policy-version">{policyVersion || '?'}</code>.
        One row is written per scope (not collapsed) — revoke any of them in Settings anytime.
      </p>
    </div>
  );
}

export default function OnboardingLaunch() {
  const navigate = useNavigate();

  // Bootstrap data
  const [loading, setLoading] = useState(true);
  const [bootErr, setBootErr] = useState('');
  const [claims, setClaims] = useState(null);
  const [spectrum, setSpectrum] = useState(DEFAULT_SPECTRUM);
  const [credits, setCredits] = useState(null);
  const [policyScopes, setPolicyScopes] = useState([]);
  const [policyVersion, setPolicyVersion] = useState('');

  // Spectrum + wave state
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewErr, setPreviewErr] = useState('');
  const [standingWave, setStandingWave] = useState(false);

  // Consent state — starts checked (required scopes) and user can uncheck
  // to abort. Both required for launch — the backend enforces this.
  const [consentChecked, setConsentChecked] = useState(LAUNCH_SCOPES);

  // Authorize state
  const [authorizing, setAuthorizing] = useState(false);
  const [authorizeErr, setAuthorizeErr] = useState(null);
  const [result, setResult] = useState(null);

  const bootstrap = useCallback(async () => {
    setLoading(true); setBootErr('');
    try {
      const [claimsR, specR, credR, polR] = await Promise.all([
        api.get('/api/v1/claims'),
        api.get('/api/v1/spectrum/suggest'),
        api.get('/api/v1/credits/me'),
        api.get('/api/v1/meta/policy'),
      ]);
      setClaims(claimsR.data);
      setSpectrum({ ...DEFAULT_SPECTRUM, ...specR.data });
      setCredits(credR.data);
      setPolicyScopes(polR.data?.scopes || []);
      setPolicyVersion(polR.data?.policy_text_version || '');
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') {
        setBootErr(`This screen needs the "${detail.scope}" consent scope. Grant it in Settings and reload.`);
      } else {
        setBootErr(e?.response?.data?.detail?.message
          || e?.response?.data?.detail
          || e?.message
          || 'Could not load launch data.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { bootstrap(); }, [bootstrap]);

  const refreshPreview = useCallback(async () => {
    setPreviewLoading(true); setPreviewErr('');
    try {
      const params = new URLSearchParams();
      if (spectrum.radius_mi != null) params.set('within_mi', String(spectrum.radius_mi));
      params.set('cap', String(DEFAULT_WAVE_CAP));
      const q = params.toString() ? `?${params.toString()}` : '';
      const r = await api.get(`/api/v1/wave/preview${q}`);
      setPreview(r.data);
    } catch (e) {
      if (e?.response?.status === 403) {
        setPreviewErr('Wave preview needs the "submit_applications" consent scope. Grant it in Settings first.');
      } else {
        setPreviewErr(e?.response?.data?.detail?.message
          || e?.response?.data?.detail
          || e?.message
          || 'Preview failed.');
      }
    } finally {
      setPreviewLoading(false);
    }
  }, [spectrum.radius_mi]);

  // Fetch preview whenever radius changes (initial + edits).
  useEffect(() => {
    if (!loading && !bootErr) refreshPreview();
  }, [loading, bootErr, refreshPreview]);

  const allRequiredConsentsOn = useMemo(
    () => LAUNCH_SCOPES.every((k) => consentChecked.includes(k)),
    [consentChecked],
  );

  const canAuthorize = !authorizing && allRequiredConsentsOn && !loading && !bootErr;

  const toggleConsent = (key) => {
    setConsentChecked((prev) => (prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]));
  };

  const patchSpectrum = (upd) => setSpectrum((s) => ({ ...s, ...upd }));

  const doAuthorize = async () => {
    setAuthorizing(true); setAuthorizeErr(null);
    try {
      const payload = {
        preferences: {
          role_families: [],
          locations: [],
          remote_ok: true,
          salary_floor_usd: spectrum.pay_floor,
          search_intensity: 'medium',
          employer_include: [],
          employer_exclude: [],
          notes: (spectrum.titles || []).length
            ? `Launch titles: ${spectrum.titles.join(', ')}`
            : null,
          booking_url: null,
        },
        wave_scope: {
          lane: null,
          within_mi: spectrum.radius_mi,
          family: null,
          cap: DEFAULT_WAVE_CAP,
          standing_wave: !!standingWave,
        },
        consents: consentChecked,
        policy_text_version: policyVersion,
      };
      const { data } = await api.post('/api/v1/onboarding/launch', payload, withIdempotency());
      setResult(data);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      const status = e?.response?.status;
      setAuthorizeErr({
        status,
        error: detail?.error,
        step: detail?.step,
        message: detail?.message || (typeof detail === 'string' ? detail : null) || e?.message || 'Launch failed.',
      });
    } finally {
      setAuthorizing(false);
    }
  };

  // ---------- Rendering ----------

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto" data-testid="onboarding-launch-loading">
        <LoadingBlock label="Preparing your launch…" />
      </div>
    );
  }

  if (bootErr) {
    return (
      <div className="max-w-3xl mx-auto" data-testid="onboarding-launch-error">
        <ErrorBlock message={bootErr} onRetry={bootstrap} />
      </div>
    );
  }

  if (result) {
    return (
      <div className="max-w-3xl mx-auto animate-fadeIn" data-testid="onboarding-launch-success">
        <Card>
          <CardHeader
            title="Launched"
            subtitle="Attested, spectrum saved, consents recorded, wave queued."
            action={<CheckCircle2 className="h-6 w-6 text-teal-500" />}
          />
          <div className="space-y-3 text-sm">
            <div className="flex items-center gap-2">
              <Fingerprint className="h-4 w-4 muted" />
              <span data-testid="launch-success-attested">
                {result.attest?.attested_count ?? 0} claims attested
              </span>
              {result.attest?.claim_set_hash && (
                <code className="text-[10px] muted font-mono truncate max-w-[280px]" title={result.attest.claim_set_hash}>
                  {result.attest.claim_set_hash.slice(0, 22)}…
                </code>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Radar className="h-4 w-4 muted" />
              <span data-testid="launch-success-queued">
                {result.wave?.queued_count ?? 0} job{(result.wave?.queued_count ?? 0) === 1 ? '' : 's'} queued
              </span>
              {result.wave?.standing_wave && (
                <span className="pill pill-accent text-[11px]" data-testid="launch-success-standing-on">
                  Standing Wave · ON
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 muted" />
              <span data-testid="launch-success-consents">
                {result.consent_row_ids?.length ?? 0} consent row{(result.consent_row_ids?.length ?? 0) === 1 ? '' : 's'} written (verbatim per scope)
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 mt-6">
            <Button
              variant="accent"
              onClick={() => navigate('/applications')}
              data-testid="launch-success-cta-applications"
            >
              View queued applications
            </Button>
            <Button
              variant="ghost"
              onClick={() => navigate('/feed')}
              data-testid="launch-success-cta-feed"
            >
              Back to feed
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  // ---------- Main compose view ----------
  const zeroCredits = credits && !credits.is_unlimited && (credits.balance ?? 0) <= 0;

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-fadeIn" data-testid="onboarding-launch">
      <div>
        <div className="flex items-center gap-3">
          <Rocket className="h-6 w-6 text-teal-500" />
          <h1 className="text-2xl font-semibold">Approve & Launch</h1>
        </div>
        <p className="muted text-sm mt-1">
          One tap combines four actions: attest your Passport, confirm your
          spectrum, preview the first wave, and authorize the auto-apply lane.
          Every step is honest and revocable.
        </p>
      </div>

      <CreditsBanner credits={credits} />

      <Card>
        <StepBadge n="1" title="Attest your Passport" subtitle="SHA-256 hash pinned to your consent ledger." icon={Fingerprint} />
        <div className="mt-4">
          <AttestSummary claims={claims} loading={false} />
        </div>
      </Card>

      <Card>
        <StepBadge n="2" title="Confirm your spectrum" subtitle="Suggested from your Passport — edit anytime." icon={Radar} />
        <div className="mt-4">
          <SpectrumStep spectrum={spectrum} editable onChange={patchSpectrum} />
        </div>
      </Card>

      <Card>
        <StepBadge n="3" title="Preview the first wave" subtitle="Dry-run against live postings; hard gates + rolling 30-day cap applied." icon={Radio} />
        <div className="mt-4">
          <WavePreviewStep
            preview={preview}
            loading={previewLoading}
            error={previewErr}
            onRefresh={refreshPreview}
          />
          <label className="flex items-center gap-2 text-xs mt-3 cursor-pointer">
            <input
              type="checkbox"
              checked={standingWave}
              onChange={(e) => setStandingWave(e.target.checked)}
              className="h-4 w-4 rounded border-line dark:border-line-dark accent-emerald-700"
              data-testid="launch-standing-wave-toggle"
            />
            <span>
              Turn on Standing Wave — auto-queue matching new arrivals on future refresh cycles (cap still enforced).
            </span>
          </label>
        </div>
      </Card>

      <Card>
        <StepBadge n="4" title="Consent — verbatim per scope" subtitle="One consent row is written per scope. Not collapsed." icon={ShieldCheck} />
        <div className="mt-4">
          <ConsentStep
            scopes={policyScopes}
            checked={consentChecked}
            onToggle={toggleConsent}
            policyVersion={policyVersion}
          />
        </div>
      </Card>

      {/* Authorize footer */}
      <div className="sticky bottom-2 z-10">
        <Card>
          <div className="flex items-start gap-4 flex-wrap">
            <div className="min-w-0 flex-1">
              {zeroCredits && (
                <div
                  className="rounded-md border border-red-500/40 bg-red-500/5 px-3 py-2 text-xs mb-2"
                  data-testid="launch-authorize-402-warning"
                >
                  Authorizing with 0 credits: the wave will queue, but the first
                  auto-dispatch will return{' '}
                  <code className="font-mono">HTTP 402 · paused_no_credits</code>{' '}
                  and park until you refill.
                </div>
              )}
              {authorizeErr && (
                <div
                  className="rounded-md border border-red-500/40 bg-red-500/5 px-3 py-2 text-xs mb-2"
                  data-testid="launch-authorize-error"
                >
                  <div className="font-semibold text-red-700 dark:text-red-300 flex items-center gap-2">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    Launch failed
                    {authorizeErr.status ? <span className="muted font-mono">HTTP {authorizeErr.status}</span> : null}
                  </div>
                  <div className="muted mt-1">
                    {authorizeErr.step && (
                      <>step: <code className="font-mono">{authorizeErr.step}</code> · </>
                    )}
                    {authorizeErr.error && (
                      <>error: <code className="font-mono">{authorizeErr.error}</code> · </>
                    )}
                    {authorizeErr.message}
                  </div>
                </div>
              )}
              {!allRequiredConsentsOn && (
                <div
                  className="rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs mb-2"
                  data-testid="launch-authorize-missing-consents"
                >
                  All two launch consents are required. Re-check the boxes above to enable Authorize.
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Button
                variant="ghost"
                onClick={() => navigate('/passport')}
                data-testid="launch-authorize-cancel"
              >
                Not yet
              </Button>
              <Button
                variant="accent"
                disabled={!canAuthorize}
                loading={authorizing}
                onClick={doAuthorize}
                data-testid="launch-authorize-btn"
              >
                {authorizing ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Launching…
                  </>
                ) : (
                  <>
                    <Rocket className="h-4 w-4" /> Authorize & Launch
                  </>
                )}
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
