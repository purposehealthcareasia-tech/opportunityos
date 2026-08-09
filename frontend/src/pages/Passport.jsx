import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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

  const reset = useCallback(() => {
    setFile(null); setError(''); setStage(null); setDocumentId(null); setMeta(null);
    if (fileRef.current) fileRef.current.value = '';
  }, []);

  const onPick = (f) => {
    setError('');
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
    setError(''); setStage('uploading');
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
          onCompleted?.();
        } else if (data.parse_status === 'failed') {
          setPolling(false);
          setError(data.parse_error || 'Parse failed.');
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

function ManualClaimModal({ type, sensitivity = 'normal', onClose, onSubmit }) {
  const [draft, setDraft] = useState('{\n  "name": ""\n}');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');
  const submit = async () => {
    setErr('');
    try {
      const value = JSON.parse(draft);
      setSubmitting(true);
      await onSubmit(value);
      onClose();
    } catch {
      setErr('Value must be valid JSON.');
    } finally { setSubmitting(false); }
  };
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4 animate-fadeIn">
      <div className="card max-w-lg w-full p-6">
        <CardHeader title={`Add a manual ${type} claim`} subtitle="You are authoring this claim yourself. It will be marked user_provided and immediately approved." />
        <textarea
          className="field-input font-mono text-xs h-56"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        {err && <p className="text-xs text-red-600 mt-2">{err}</p>}
        <div className="flex items-center justify-end gap-2 mt-4">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button variant="accent" onClick={submit} loading={submitting}>Add claim</Button>
        </div>
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
                  {d.parse_error && <p className="text-xs text-red-600 mt-1">{d.parse_error}</p>}
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
  const addManual = async (type, sensitivity, value) => {
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
    <div className="max-w-5xl mx-auto space-y-6 animate-fadeIn">
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
          <EmptyBlock
            title="No claims yet"
            hint="Upload a résumé to parse it into structured draft claims, or add claims manually below."
            action={<Button variant="accent" onClick={() => setTab('upload')}>Upload résumé</Button>}
          />
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
                  <button key={t} type="button" onClick={() => setManualModal({ type: t, sensitivity: 'normal' })} className="pill pill-neutral hover:bg-neutral-100 dark:hover:bg-neutral-800">
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
          onSubmit={(value) => addManual(manualModal.type, manualModal.sensitivity, value)}
        />
      )}
    </div>
  );
}
