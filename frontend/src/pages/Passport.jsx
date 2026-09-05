import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Upload, FileText, CheckCircle2, XCircle, ShieldCheck, Lock, Pencil, RotateCcw, Plus, Loader2 } from 'lucide-react';
import { api, withIdempotency } from '../lib/api';
import { LoadingBlock, ErrorBlock, EmptyBlock } from '../lib/scope';
import { prettyValue, sourceChip, sortGroups, CLAIM_TYPE_ORDER } from '../lib/utils';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';

const MAX_MB = 10;
const ALLOWED_MIMES = new Set([
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]);

const STAGE_LABELS = {
  uploading: 'Uploading to storage…',
  queued: 'Queued for parsing…',
  extracting: 'Extracting text…',
  parsing: 'Parsing résumé with LLM…',
  completed: 'Parse complete',
  failed: 'Parse failed',
};

// Phase 6 prod-UX fix (2026-08-12): short human-readable labels for the
// history list. The upload panel uses the full ParseFailureCard copy
// (headline/body/tip/cta) fetched from `/parse-status`; this shorter map
// is used only in the compact document-history list rows.
const PARSE_ERROR_SHORT = {
  scanned_pdf_suspected: 'PDF looks scanned — re-upload as DOCX or a text-based PDF.',
  docx_extractor_blind: 'DOCX uses shapes/headers we can\u2019t read — re-save as plain DOCX.',
  too_little_content: 'Very little text — add more content and re-upload.',
  extractor_error: "We couldn't open this file — it may be corrupt or protected.",
  extract_failed: "We couldn't open this file — it may be corrupt or protected.",
  pipeline_error: 'Something went wrong on our side — please try again.',
  extracted_text_too_short: 'Too little text extracted — re-upload.',
};

// Hoisted from an inline JSX literal (2026-08-09 code-review remediation).
// The stage order is a module-level constant and the 4-bar progress
// derivation is memoized against `stage`. Deduping via `indexOf(s) === i`
// is not needed since the source is already unique.
const STAGE_ORDER = ['uploading', 'queued', 'extracting', 'parsing', 'completed'];
const STAGE_BARS = STAGE_ORDER.slice(0, 4);

function StageProgressBars({ stage }) {
  const bars = React.useMemo(() => {
    const curIdx = STAGE_ORDER.indexOf(stage);
    return STAGE_BARS.map((s) => ({
      key: s,
      filled: curIdx >= STAGE_ORDER.indexOf(s),
    }));
  }, [stage]);
  return (
    <div className="mt-3 grid grid-cols-4 gap-1">
      {bars.map((b) => (
        <div
          key={b.key}
          className={`h-1 rounded-full ${b.filled ? 'bg-accent' : 'bg-neutral-200 dark:bg-neutral-800'}`}
        />
      ))}
    </div>
  );
}

function UploadPanel({ onCompleted }) {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');
  const [stage, setStage] = useState(null);
  const [documentId, setDocumentId] = useState(null);
  const [meta, setMeta] = useState(null);
  const [polling, setPolling] = useState(false);
  // Phase 6 prod-UX fix (2026-08-12): friendly parse-failure copy + OCR
  // offer envelope. Keeps raw slug as small-print support metadata.
  const [failure, setFailure] = useState(null);

  const reset = useCallback(() => {
    setFile(null); setError(''); setStage(null); setDocumentId(null); setMeta(null); setFailure(null);
    if (fileRef.current) fileRef.current.value = '';
  }, []);

  const onPick = (f) => {
    setError(''); setFailure(null);
    if (!f) return;
    if (!ALLOWED_MIMES.has(f.type) && !/\.(pdf|docx)$/i.test(f.name)) {
      setError('Only PDF and DOCX files are accepted.');
      return;
    }
    if (f.size > MAX_MB * 1024 * 1024) {
      setError(`File exceeds the ${MAX_MB} MB limit.`);
      return;
    }
    setFile(f);
  };

  const startUpload = async () => {
    if (!file) return;
    setError(''); setFailure(null); setStage('uploading');
    try {
      const fd = new FormData();
      fd.append('file', file);
      const { data } = await api.post('/api/v1/documents/resume', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setDocumentId(data.document.id);
      setStage(data.document.parse_status);
      setPolling(true);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') {
        setError('You must grant the process_career_data consent to upload a résumé.');
      } else if (detail?.error === 'unsupported_type') setError(detail.message);
      else if (detail?.error === 'file_too_large') setError(detail.message);
      else setError('Upload failed. Please try again.');
      setStage(null);
    }
  };

  useEffect(() => {
    if (!polling || !documentId) return undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        const { data } = await api.get(`/api/v1/documents/${documentId}/parse-status`);
        if (cancelled) return;
        setStage(data.parse_status);
        setMeta(data.parse_meta || {});
        if (data.parse_status === 'completed') {
          setPolling(false);
          setFailure(null);
          onCompleted?.();
        } else if (data.parse_status === 'failed') {
          setPolling(false);
          // Prefer the classifier-driven friendly copy envelope; fall back
          // to raw slug only when the envelope is missing (very old rows).
          if (data.parse_error_copy) {
            setFailure({
              slug: data.parse_error,
              copy: data.parse_error_copy,
              ocrOffer: data.ocr_offer || null,
              meta: data.parse_meta || {},
            });
            setError('');
          } else {
            setError(data.parse_error || 'Parse failed.');
          }
        }
      } catch (e) { console.debug('parse-status poll transient failure', e); }
    };
    tick();
    const t = setInterval(tick, 2500);
    return () => { cancelled = true; clearInterval(t); };
  }, [polling, documentId, onCompleted]);

  const isBusy = polling || stage === 'uploading';

  return (
    <Card>
      <CardHeader title="Upload a résumé" subtitle="PDF or DOCX up to 10 MB. Parsed into draft claims by gpt-5 — nothing is auto-approved." />
      <div className="space-y-4">
        <div className="rounded-card border border-dashed border-line dark:border-line-dark p-6 text-center">
          {file ? (
            <div className="flex items-center justify-center gap-3">
              <FileText className="h-5 w-5 muted" />
              <div className="text-sm">{file.name} <span className="muted">· {(file.size / 1024).toFixed(0)} KB</span></div>
              <button type="button" onClick={reset} className="text-xs muted underline">clear</button>
            </div>
          ) : (
            <div>
              <Upload className="h-6 w-6 mx-auto muted" />
              <p className="text-sm muted mt-2">Drag & drop or choose a file.</p>
              <button type="button" onClick={() => fileRef.current?.click()} className="btn btn-secondary mt-3">Choose file</button>
            </div>
          )}
          <input ref={fileRef} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" className="hidden" onChange={(e) => onPick(e.target.files?.[0])} />
        </div>

        {error && <ErrorBlock message={error} onRetry={reset} />}

        {failure && (
          <div
            className="rounded-card border border-red-500/40 bg-red-500/5 p-4 space-y-3"
            data-testid={`parse-failure-card-${failure.slug}`}
          >
            <div className="flex items-start gap-3">
              <XCircle className="h-5 w-5 text-red-500 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="font-semibold" data-testid="parse-failure-headline">
                  {failure.copy?.headline}
                </div>
                <p className="text-sm mt-1" data-testid="parse-failure-body">
                  {failure.copy?.body}
                </p>
                {failure.copy?.tip && (
                  <p className="text-xs muted mt-1" data-testid="parse-failure-tip">
                    {failure.copy.tip}
                  </p>
                )}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 pl-8">
              <Button
                variant="accent"
                onClick={reset}
                data-testid="parse-failure-reupload-btn"
              >
                {failure.copy?.cta || 'Upload a different file'}
              </Button>
              {failure.ocrOffer && (
                <Button
                  variant="secondary"
                  disabled={!failure.ocrOffer.available}
                  data-testid="parse-failure-ocr-btn"
                  title={
                    failure.ocrOffer.available
                      ? 'Attempt OCR — claims still require your explicit approval'
                      : 'OCR is not currently available on this deployment'
                  }
                >
                  {failure.ocrOffer.label}
                  {!failure.ocrOffer.available && ' (unavailable)'}
                </Button>
              )}
            </div>
            <p className="text-[10px] muted pl-8 font-mono" data-testid="parse-failure-support-slug">
              support ref: {failure.slug}
              {failure.meta?.pdf_num_pages != null && ` · pages=${failure.meta.pdf_num_pages}`}
              {failure.meta?.extracted_chars != null && ` · chars=${failure.meta.extracted_chars}`}
              {failure.meta?.file_bytes != null && ` · bytes=${failure.meta.file_bytes}`}
            </p>
          </div>
        )}

        {stage && (
          <div className="rounded-card border border-line dark:border-line-dark p-4">
            <div className="flex items-center gap-3">
              {stage === 'completed' ? (
                <CheckCircle2 className="h-5 w-5 text-accent" />
              ) : stage === 'failed' ? (
                <XCircle className="h-5 w-5 text-red-500" />
              ) : (
                <Loader2 className="h-4 w-4 animate-spin text-accent" />
              )}
              <div className="text-sm font-medium">{STAGE_LABELS[stage] || stage}</div>
            </div>
            <StageProgressBars stage={stage} />
            {stage === 'completed' && meta && (
              <p className="text-xs muted mt-3">Model used: <span className="font-mono">{meta.model_used}</span> · {meta.inserted_claim_count} draft claims created (all pending your approval).</p>
            )}
          </div>
        )}

        <div className="flex items-center justify-between">
          <p className="text-xs muted">No account passwords ever. No scraping. Nothing here is auto-submitted.</p>
          <Button onClick={startUpload} disabled={!file || isBusy} loading={isBusy && stage === 'uploading'}>Upload & parse</Button>
        </div>
      </div>
    </Card>
  );
}

function SourcePill({ src }) {
  const chip = sourceChip(src);
  return <span className={chip.tone === 'accent' ? 'pill pill-accent' : 'pill pill-neutral'}>{chip.label}</span>;
}

function ConfidenceBar({ value }) {
  if (value == null) return <span className="text-xs muted">no confidence</span>;
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 bg-neutral-200 dark:bg-neutral-800 rounded-full overflow-hidden">
        <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[11px] muted">{Math.round(pct)}%</span>
    </div>
  );
}

function ClaimRow({ claim, onApprove, onReject, onEdit, busy }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => JSON.stringify(claim.value, null, 2));
  const status = claim.status || 'pending';
  const statusPill = {
    approved: 'pill pill-accent',
    rejected: 'border border-red-500/30 text-red-600 dark:text-red-400 pill',
    pending: 'pill pill-neutral',
    superseded: 'pill pill-neutral',
  }[status] || 'pill pill-neutral';

  const submitEdit = async () => {
    try {
      const parsed = JSON.parse(draft);
      await onEdit(parsed);
      setEditing(false);
    } catch {
      alert('Value must be valid JSON.');
    }
  };

  return (
    <div className="border border-line dark:border-line-dark rounded-card p-4 bg-white dark:bg-neutral-900">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {editing ? (
            <textarea
              className="field-input font-mono text-xs h-40 w-full"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          ) : (
            <p className="text-sm text-ink dark:text-ink-dark leading-relaxed break-words">{prettyValue(claim.value)}</p>
          )}
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <SourcePill src={claim.source} />
            <ConfidenceBar value={claim.confidence} />
            <span className={statusPill}>{status}</span>
            {claim.version > 1 && <span className="pill pill-neutral">v{claim.version}</span>}
          </div>
        </div>
        <div className="flex-shrink-0 flex items-center gap-1">
          {editing ? (
            <>
              <Button size="sm" variant="accent" onClick={submitEdit} loading={busy}>Save edit</Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
            </>
          ) : status === 'pending' ? (
            <>
              <Button size="sm" variant="accent" onClick={onApprove} loading={busy}>Approve</Button>
              <Button size="sm" variant="secondary" onClick={() => setEditing(true)}><Pencil className="h-3 w-3" />Edit</Button>
              <Button size="sm" variant="ghost" onClick={onReject} loading={busy}>Reject</Button>
            </>
          ) : status === 'rejected' ? (
            <Button size="sm" variant="secondary" onClick={onApprove} loading={busy}><RotateCcw className="h-3 w-3" />Re-approve</Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)}><Pencil className="h-3 w-3" />Edit</Button>
          )}
        </div>
      </div>
    </div>
  );
}

function ClaimGroup({ type, claims, onBulkApprove, onApprove, onReject, onEdit, onAddManual, busyId }) {
  const pending = claims.filter((c) => c.status === 'pending');
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide muted">{type}</h3>
        <div className="flex items-center gap-2">
          {pending.length > 1 && (
            <Button size="sm" variant="secondary" onClick={onBulkApprove}>
              <ShieldCheck className="h-3 w-3" /> Approve all {pending.length}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onAddManual}><Plus className="h-3 w-3" /> Add</Button>
        </div>
      </div>
      {claims.map((c) => (
        <ClaimRow
          key={c.id}
          claim={c}
          busy={busyId === c.id}
          onApprove={() => onApprove(c)}
          onReject={() => onReject(c)}
          onEdit={(newVal) => onEdit(c, newVal)}
        />
      ))}
    </div>
  );
}

function SealedSection({ claims, onEdit, onAddManual }) {
  if (!claims.length) return null;
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <Lock className="h-4 w-4 text-accent" />
          <h3 className="text-sm font-semibold">Sealed section</h3>
          <span className="pill pill-neutral">only you see the real values</span>
        </div>
        <Button size="sm" variant="ghost" onClick={onAddManual}><Plus className="h-3 w-3" /> Add</Button>
      </div>
      <p className="text-xs muted max-w-2xl leading-relaxed">
        Sealed claims (work authorization, visa timelines, and anything you mark sensitive) are
        masked for admins and support. They’re never released to an employer without your explicit,
        per-application approval in a later phase.
      </p>
      {claims.map((c) => (
        <ClaimRow
          key={c.id}
          claim={c}
          onApprove={() => {}}
          onReject={() => {}}
          onEdit={(newVal) => onEdit(c, newVal)}
        />
      ))}
    </div>
  );
}

// Phase 6 P0 hotfix (2026-08-13 Gate) — structured manual-claim entry.
// Historical UI was a raw JSON textarea; onboarding-blocked users
// (parse-pipeline broken) could not reach activation without a working
// parse. Backend value-key contracts pinned by
// `domains/claims/schema.py::VALUE_KEYS_BY_TYPE`.
// Identity uses `legal_first / legal_last / preferred_name` — matches
// `IDENTITY_VALUE_KEYS`. Backend preflight `_canonical_identity` derives
// the outbound `name` from `preferred_name` OR `f"{legal_first} {legal_last}"`.
const MANUAL_FIELDS_BY_TYPE = {
  identity:    [
    { key: 'legal_first',    label: 'Legal first name',       placeholder: 'e.g. Jane',                        required: true },
    { key: 'legal_last',     label: 'Legal last name',        placeholder: 'e.g. Doe',                         required: true },
    { key: 'preferred_name', label: 'Preferred name (optional)', placeholder: 'What should employers call you? e.g. J.D.', required: false },
  ],
  contact:     [
    { key: 'email',       label: 'Email',                required: false, placeholder: 'you@example.com' },
    { key: 'phone',       label: 'Phone',                required: false, placeholder: '+1 555 …' },
  ],
  location:    [
    { key: 'city',        label: 'City',                 required: false, placeholder: 'San Francisco' },
    { key: 'state',       label: 'State / region',       required: false, placeholder: 'CA' },
    { key: 'country',     label: 'Country',              required: false, placeholder: 'USA' },
  ],
  education:   [
    { key: 'institution', label: 'School / institution', required: true,  placeholder: 'e.g. UC Berkeley' },
    { key: 'degree',      label: 'Degree',               required: false, placeholder: 'e.g. BS Computer Science' },
    { key: 'field',       label: 'Field of study',       required: false, placeholder: 'e.g. Software Engineering' },
    { key: 'start',       label: 'Start (YYYY-MM)',      required: false, placeholder: '2018-08' },
    { key: 'end',         label: 'End (YYYY-MM)',        required: false, placeholder: '2022-05' },
  ],
  employment:  [
    { key: 'company',     label: 'Company',              required: true,  placeholder: 'e.g. Acme Corp' },
    { key: 'role',        label: 'Role / title',         required: true,  placeholder: 'e.g. Senior Backend Engineer' },
    { key: 'start',       label: 'Start (YYYY-MM)',      required: false, placeholder: '2021-04' },
    { key: 'end',         label: 'End (YYYY-MM or Present)', required: false, placeholder: '2024-12' },
    { key: 'summary',     label: 'One-line summary',     required: false, placeholder: 'Led migration of monolith to microservices', textarea: true },
  ],
  skill:       [{ key: 'name',        label: 'Skill',                required: true,  placeholder: 'e.g. Python' }],
  project:     [
    { key: 'name',        label: 'Project name',         required: true,  placeholder: 'e.g. Latency dashboard' },
    { key: 'description', label: 'Description',          required: false, placeholder: 'What it does + your role', textarea: true },
  ],
  certification: [{ key: 'name', label: 'Certification', required: true, placeholder: 'e.g. AWS Solutions Architect' }],
  work_auth:   [
    { key: 'status',      label: 'Status',               required: true,  placeholder: 'e.g. us_citizen, ead_opt, h1b' },
    { key: 'notes',       label: 'Notes',                required: false, placeholder: 'Optional context', textarea: true },
  ],
  visa_timeline: [
    { key: 'visa',        label: 'Visa type',            required: true,  placeholder: 'e.g. H-1B, F-1' },
    { key: 'expires',     label: 'Expires (YYYY-MM-DD)', required: false, placeholder: '2027-09-30' },
  ],
};
const MANUAL_TYPE_LABELS = {
  identity: 'Identity',
  contact: 'Contact',
  location: 'Location',
  education: 'Education',
  employment: 'Employment',
  skill: 'Skill',
  project: 'Project',
  certification: 'Certification',
  work_auth: 'Work authorization',
  visa_timeline: 'Visa timeline',
};

function ManualClaimModal({ type: initialType, sensitivity = 'normal', onClose, onSubmit }) {
  const [type, setType] = useState(initialType || 'identity');
  const [values, setValues] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');

  const fields = MANUAL_FIELDS_BY_TYPE[type] || [];

  const patch = (k, v) => setValues((p) => ({ ...p, [k]: v }));

  const submit = async () => {
    setErr('');
    const value = {};
    for (const f of fields) {
      const raw = (values[f.key] ?? '').toString();
      const v = raw.trim();
      if (v) value[f.key] = v;
      if (f.required && !v) {
        setErr(`Please fill ${f.label}.`);
        return;
      }
    }
    setSubmitting(true);
    try {
      await onSubmit({ type, value });
      onClose();
    } catch (e) {
      setErr(e?.response?.data?.detail?.message || e?.message || 'Failed to add claim.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4 animate-fadeIn"
      data-testid="manual-claim-modal"
    >
      <div className="card max-w-lg w-full p-6 max-h-[90vh] overflow-y-auto">
        <CardHeader
          title="Add a claim manually"
          subtitle="You author it, we mark it user_provided and save it as a pending draft — you tap Approve on the row to attest. Full provenance on your Passport."
        />

        <div className="mt-3">
          <label className="field-label" htmlFor="manual-claim-type">Kind of claim</label>
          <select
            id="manual-claim-type"
            className="field-input"
            value={type}
            onChange={(e) => { setType(e.target.value); setValues({}); setErr(''); }}
            data-testid="manual-claim-type-select"
          >
            {Object.keys(MANUAL_FIELDS_BY_TYPE).map((k) => (
              <option key={k} value={k}>{MANUAL_TYPE_LABELS[k] || k}</option>
            ))}
          </select>
        </div>

        <div className="space-y-3 mt-4">
          {fields.map((f) => (
            <div key={f.key}>
              <label className="field-label" htmlFor={`manual-claim-field-${f.key}`}>
                {f.label}{f.required && <span className="text-red-500 ml-1">*</span>}
              </label>
              {f.textarea ? (
                <textarea
                  id={`manual-claim-field-${f.key}`}
                  className="field-input min-h-[64px]"
                  placeholder={f.placeholder}
                  value={values[f.key] || ''}
                  onChange={(e) => patch(f.key, e.target.value)}
                  data-testid={`manual-claim-field-${f.key}`}
                />
              ) : (
                <input
                  id={`manual-claim-field-${f.key}`}
                  type="text"
                  className="field-input"
                  placeholder={f.placeholder}
                  value={values[f.key] || ''}
                  onChange={(e) => patch(f.key, e.target.value)}
                  data-testid={`manual-claim-field-${f.key}`}
                />
              )}
            </div>
          ))}
        </div>

        {err && (
          <p className="text-xs text-red-600 mt-3" data-testid="manual-claim-error">{err}</p>
        )}

        <div className="flex items-center justify-end gap-2 mt-5">
          <Button variant="secondary" onClick={onClose} data-testid="manual-claim-cancel">Cancel</Button>
          <Button
            variant="accent"
            onClick={submit}
            loading={submitting}
            data-testid="manual-claim-submit"
          >
            Add claim
          </Button>
        </div>
        <p className="text-[10px] muted mt-3 text-center">
          Provenance: <code className="font-mono">source.kind = user_provided</code>.
          Sensitivity: <code className="font-mono">{sensitivity}</code>.
        </p>
      </div>
    </div>
  );
}

function ActivationBanner({ status, onActivate, activating }) {
  if (!status) return null;
  if (status.activated) {
    return (
      <div className="card p-5 border-accent/40 bg-accent/5">
        <div className="flex items-center gap-3">
          <ShieldCheck className="h-5 w-5 text-accent" />
          <div>
            <p className="text-sm font-semibold">Passport activated.</p>
            <p className="text-xs muted mt-0.5">Downstream features that need an activated passport are now unlocked when they ship.</p>
          </div>
        </div>
      </div>
    );
  }
  const req = status.requirements || {};
  const items = [
    { key: 'identity_approved', label: 'At least one approved identity claim', met: req.identity_approved },
    { key: 'education_or_employment_approved', label: 'At least one approved education or employment claim', met: req.education_or_employment_approved },
  ];
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold">Activate your Passport</p>
          <p className="text-xs muted mt-0.5">Activation is server-checked. Meet the checklist below and the button turns on.</p>
          <ul className="space-y-1 mt-3">
            {items.map((i) => (
              <li key={i.key} className="flex items-center gap-2 text-sm">
                {i.met ? <CheckCircle2 className="h-4 w-4 text-accent" /> : <XCircle className="h-4 w-4 text-red-500" />}
                <span className={i.met ? '' : 'muted'}>{i.label}</span>
              </li>
            ))}
          </ul>
        </div>
        <Button variant="accent" disabled={!status.can_activate} loading={activating} onClick={onActivate}>Activate Passport</Button>
      </div>
    </div>
  );
}

const DOC_STATUS_ICON = {
  completed: { Icon: CheckCircle2, cls: 'text-accent' },
  failed: { Icon: XCircle, cls: 'text-red-500' },
};
function docStatusVisual(status) {
  return DOC_STATUS_ICON[status] || { Icon: Loader2, cls: 'text-accent animate-spin' };
}

function DocumentHistory() {
  const [docs, setDocs] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/documents/me');
      setDocs(data.documents || []);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.error !== 'consent_required') setError('Could not load your document history.');
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (docs === null && !error) return null;
  return (
    <Card>
      <CardHeader
        title="Résumé history"
        subtitle="Every résumé you've uploaded, with parse status and model used. We never delete history — supersedes-only."
        action={<button type="button" onClick={load} className="text-xs muted underline" data-testid="doc-history-refresh">Refresh</button>}
      />
      {error && <ErrorBlock message={error} onRetry={load} />}
      {docs && docs.length === 0 && (
        <p className="muted text-sm">No résumés uploaded yet.</p>
      )}
      {docs && docs.length > 0 && (
        <ul className="divide-y divide-line dark:divide-line-dark" data-testid="doc-history-list">
          {docs.map((d) => {
            const { Icon: StatusIcon, cls: iconCls } = docStatusVisual(d.parse_status);
            return (
              <li key={d.id} className="py-3 flex items-center justify-between gap-3" data-testid={`doc-history-row-${d.id}`}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 muted" />
                    <span className="text-sm font-medium truncate">{d.original_filename || 'resume'}</span>
                    <span className="pill pill-neutral">{Math.round((d.size_bytes || 0) / 1024)} KB</span>
                  </div>
                  <div className="text-xs muted mt-1 flex items-center gap-2 flex-wrap">
                    <StatusIcon className={`h-3 w-3 ${iconCls}`} />
                    <span className="font-mono">{d.parse_status}</span>
                    {d.parse_meta?.model_used && (
                      <>
                        <span>·</span>
                        <span>model <span className="font-mono">{d.parse_meta.model_used}</span></span>
                      </>
                    )}
                    {typeof d.parse_meta?.inserted_claim_count === 'number' && (
                      <>
                        <span>·</span>
                        <span>{d.parse_meta.inserted_claim_count} claims created</span>
                      </>
                    )}
                    <span>·</span>
                    <span>{new Date(d.created_at).toLocaleString()}</span>
                  </div>
                  {d.parse_error && (
                    <p className="text-xs text-red-600 mt-1" data-testid="passport-doc-parse-error">
                      {PARSE_ERROR_SHORT[d.parse_error] || d.parse_error}
                    </p>
                  )}
                </div>
                <span className="text-[10px] muted font-mono truncate" title={d.sha256}>{(d.sha256 || '').slice(0, 10)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

export default function PassportPage() {
  const [tab, setTab] = useState('review');
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activationStatus, setActivationStatus] = useState(null);
  const [activating, setActivating] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [manualModal, setManualModal] = useState(null); // {type, sensitivity}
  const [searchParams, setSearchParams] = useSearchParams();

  // FYND ATLAS hotfix (2026-08-13): deep-link the "Finish Passport"
  // SmartCTA so a click on it observably OPENS the manual-claim modal
  // — even when the user is already on /passport. Fires once on
  // mount + on every param change; consumes the param so refresh
  // doesn't re-trigger the modal after they dismiss it.
  useEffect(() => {
    const action = searchParams.get('action');
    if (!action) return;
    const map = {
      'add-identity': { type: 'identity', sensitivity: 'normal' },
      'add-education': { type: 'education', sensitivity: 'normal' },
      'add-employment': { type: 'employment', sensitivity: 'normal' },
    };
    const target = map[action];
    if (target) setManualModal(target);
    // Strip the param so refresh / back doesn't re-open the modal.
    const next = new URLSearchParams(searchParams);
    next.delete('action');
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reload = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [{ data: claims }, { data: act }] = await Promise.all([
        api.get('/api/v1/claims'),
        api.get('/api/v1/passport/activation-status'),
      ]);
      setGroups(sortGroups(claims.groups || []));
      setActivationStatus(act);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') {
        setError('The process_career_data consent is required. Grant it in Settings.');
      } else setError('Could not load your Passport.');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const { sealedGroups, normalGroups } = useMemo(() => {
    const sealed = [];
    const normal = [];
    for (const g of groups) {
      const s = g.claims.filter((c) => c.sensitivity === 'sealed');
      const n = g.claims.filter((c) => c.sensitivity !== 'sealed');
      if (n.length) normal.push({ type: g.type, claims: n });
      if (s.length) sealed.push({ type: g.type, claims: s });
    }
    return { sealedGroups: sealed, normalGroups: normal };
  }, [groups]);

  const flatSealed = useMemo(() => sealedGroups.flatMap((g) => g.claims), [sealedGroups]);

  const approve = async (claim) => {
    setBusyId(claim.id);
    try {
      await api.post(`/api/v1/claims/${claim.id}/approve`, {}, withIdempotency());
      await reload();
    } finally { setBusyId(null); }
  };
  const reject = async (claim) => {
    setBusyId(claim.id);
    try {
      await api.post(`/api/v1/claims/${claim.id}/reject`, {}, withIdempotency());
      await reload();
    } finally { setBusyId(null); }
  };
  const edit = async (claim, newValue) => {
    setBusyId(claim.id);
    try {
      await api.put(`/api/v1/claims/${claim.id}`, { value: newValue }, withIdempotency());
      await reload();
    } finally { setBusyId(null); }
  };
  const bulkApprove = async (type) => {
    await api.post('/api/v1/claims/bulk-approve', { type }, withIdempotency());
    await reload();
  };
  const addManual = async ({ type, value }, sensitivity = 'normal') => {
    await api.post('/api/v1/claims', { type, sensitivity, value }, withIdempotency());
    await reload();
  };
  const activate = async () => {
    setActivating(true);
    try {
      await api.post('/api/v1/passport/activate', {}, withIdempotency());
      await reload();
    } catch (e) {
      alert(e?.response?.data?.detail?.hint || 'Activation failed.');
    } finally { setActivating(false); }
  };

  const totalClaims = useMemo(() => groups.reduce((n, g) => n + g.claims.length, 0), [groups]);
  const missingClaimTypes = useMemo(
    () => CLAIM_TYPE_ORDER.filter((t) => !groups.find((g) => g.type === t)),
    [groups],
  );

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-fadeIn" data-testid="passport-page">
      <div>
        <h1 className="text-2xl font-semibold">Career Passport</h1>
        <p className="muted mt-1 text-sm max-w-2xl">Every fact about you lives here. Nothing draft ever leaves your account. Approve what’s true, edit what needs fixing, reject what isn’t you.</p>
      </div>

      <ActivationBanner status={activationStatus} onActivate={activate} activating={activating} />

      <div className="flex items-center gap-1 border-b border-line dark:border-line-dark">
        {[
          { k: 'review', label: `Review (${totalClaims})` },
          { k: 'upload', label: 'Upload résumé' },
        ].map((t) => (
          <button key={t.k} type="button" onClick={() => setTab(t.k)} className={`px-4 py-2 text-sm -mb-px border-b-2 transition-colors ${tab === t.k ? 'border-accent text-ink dark:text-ink-dark' : 'border-transparent muted hover:text-ink dark:hover:text-ink-dark'}`}>{t.label}</button>
        ))}
      </div>

      {tab === 'upload' && (
        <>
          <UploadPanel onCompleted={() => { setTab('review'); reload(); }} />
          <DocumentHistory />
        </>
      )}

      {tab === 'review' && (
        loading ? <LoadingBlock /> :
        error ? <ErrorBlock message={error} onRetry={reload} /> :
        totalClaims === 0 ? (
          <div className="space-y-4" data-testid="passport-empty-state">
            <EmptyBlock
              title="No claims yet"
              hint="Two paths to your Passport: parse a résumé, or add claims by hand. Either works — you're always in control."
            />
            <div className="card p-5">
              <p className="text-sm font-semibold mb-2">Two paths to activate your Passport</p>
              <p className="text-xs muted mb-4">
                Activation needs one approved <span className="font-mono">identity</span> claim
                AND one approved <span className="font-mono">education</span> or{' '}
                <span className="font-mono">employment</span> claim. You can add both by hand right here.
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="accent"
                  onClick={() => setTab('upload')}
                  data-testid="empty-state-upload-btn"
                >
                  <Upload className="h-4 w-4" /> Upload résumé
                </Button>
                <span className="text-xs muted self-center px-1">or add by hand:</span>
                <Button
                  variant="secondary"
                  onClick={() => setManualModal({ type: 'identity', sensitivity: 'normal' })}
                  data-testid="empty-state-add-identity-btn"
                >
                  <Plus className="h-4 w-4" /> Add identity
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setManualModal({ type: 'education', sensitivity: 'normal' })}
                  data-testid="empty-state-add-education-btn"
                >
                  <Plus className="h-4 w-4" /> Add education
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => setManualModal({ type: 'employment', sensitivity: 'normal' })}
                  data-testid="empty-state-add-employment-btn"
                >
                  <Plus className="h-4 w-4" /> Add employment
                </Button>
              </div>
              <p className="text-[10px] muted mt-3">
                Manual claims are marked <code className="font-mono">source.kind = user_provided</code>{' '}
                and saved as pending drafts — you explicitly tap Approve on the row to attest.
                Same provenance rails as any parsed claim.
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-10">
            {normalGroups.map((g) => (
              <ClaimGroup
                key={g.type}
                type={g.type}
                claims={g.claims}
                busyId={busyId}
                onBulkApprove={() => bulkApprove(g.type)}
                onApprove={approve}
                onReject={reject}
                onEdit={edit}
                onAddManual={() => setManualModal({ type: g.type, sensitivity: 'normal' })}
              />
            ))}
            <SealedSection
              claims={flatSealed}
              onEdit={edit}
              onAddManual={() => setManualModal({ type: 'work_auth', sensitivity: 'sealed' })}
            />
            {/* Types that have no claims yet still get an add button so users can seed missing categories */}
            <div className="pt-6 border-t border-line dark:border-line-dark">
              <p className="text-xs muted mb-3">Missing a category? Add it manually.</p>
              <div className="flex flex-wrap gap-2">
                {missingClaimTypes.map((t) => (
                  <button key={t} type="button" onClick={() => setManualModal({ type: t, sensitivity: 'normal' })} className="pill pill-neutral hover:bg-neutral-100 dark:hover:bg-neutral-800" data-testid={`add-missing-category-${t}`}>
                    <Plus className="h-3 w-3" /> {t}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )
      )}

      {manualModal && (
        <ManualClaimModal
          type={manualModal.type}
          sensitivity={manualModal.sensitivity}
          onClose={() => setManualModal(null)}
          onSubmit={(payload) => addManual(payload, manualModal.sensitivity)}
        />
      )}
    </div>
  );
}
