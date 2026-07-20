import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  ArrowLeft, Sparkles, ShieldCheck, ShieldOff, AlertTriangle, CheckCircle2, XCircle,
  Undo2, Send, TestTube2, RefreshCw, FileText, Download, MessageSquare, HelpCircle, Ban,
} from 'lucide-react';
import { api, withIdempotency } from '../lib/api';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Input from '../components/ui/Input';
import { LoadingBlock, ErrorBlock } from '../lib/scope';

const REJECTION_LABELS = {
  empty_claim_ids: 'no claim IDs referenced',
  malformed_line: 'malformed line',
};
function rlabel(code) {
  if (REJECTION_LABELS[code]) return REJECTION_LABELS[code];
  if (code?.startsWith('unapproved_claim:')) return `unapproved claim (${code.slice(17, 25)}…)`;
  if (code?.startsWith('number_not_in_claims:')) return `unsupported number "${code.slice(21)}"`;
  if (code?.startsWith('date_not_in_claims:')) return `unsupported year "${code.slice(19)}"`;
  if (code?.startsWith('sensitive_leak:')) return `sensitive leak (${code.slice(15)})`;
  return code;
}

function ValidatorChip({ result, outcome, refusal }) {
  if (!result) return null;
  const passed = result.status === 'passed';
  const nRej = (result.rejected_lines || []).length;
  const nPass = (result.passed_lines || []).length;
  const cls = passed
    ? 'pill pill-accent'
    : outcome === 'template_fallback'
    ? 'pill border-amber-500/40 text-amber-700 dark:text-amber-400'
    : 'pill border-red-500/40 text-red-600 dark:text-red-400';
  const label = passed
    ? `${nPass} grounded · 0 unverified statements`
    : outcome === 'template_fallback'
    ? `AI draft failed validation — using grounded template (${nPass} lines)`
    : `${nRej} rejected · ${nPass} accepted`;
  const Icon = passed ? ShieldCheck : outcome === 'template_fallback' ? AlertTriangle : ShieldOff;
  return (
    <span className={cls} data-testid="validator-chip">
      <Icon className="h-3 w-3" /> {label}
    </span>
  );
}

function LineRow({ line, base, onAccept, onRevert, busy }) {
  const status = line.status || 'proposed';
  const cls =
    status === 'accepted' ? 'border-accent/50 bg-accent/5'
    : status === 'reverted' ? 'border-red-500/40 bg-red-500/5 opacity-70'
    : 'border-line dark:border-line-dark';
  return (
    <div className={`rounded-md border p-3 ${cls}`} data-testid={`resume-line-${line.line_id}`}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm leading-relaxed" data-testid={`resume-line-text-${line.line_id}`}>{line.text}</p>
        <span className={
          status === 'accepted' ? 'pill pill-accent flex-shrink-0'
          : status === 'reverted' ? 'pill border-red-500/40 text-red-600 dark:text-red-400 flex-shrink-0'
          : 'pill pill-neutral flex-shrink-0'
        }>{status}</span>
      </div>
      <div className="flex items-center justify-between gap-2 mt-2">
        <div className="text-[10px] muted font-mono">
          claims: {line.claim_ids?.map((id) => id.slice(0, 6)).join(', ') || '—'}
        </div>
        <div className="flex items-center gap-1">
          {status !== 'accepted' && (
            <Button size="sm" variant="secondary" onClick={() => onAccept(line.line_id)} loading={busy === line.line_id + ':accept'} data-testid={`resume-line-accept-${line.line_id}`}>
              <CheckCircle2 className="h-3 w-3" /> Accept
            </Button>
          )}
          {status !== 'reverted' && (
            <Button size="sm" variant="ghost" onClick={() => onRevert(line.line_id)} loading={busy === line.line_id + ':revert'} data-testid={`resume-line-revert-${line.line_id}`}>
              <Undo2 className="h-3 w-3" /> Revert
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function ResumeDiffTab({ packet, onReload }) {
  const [busy, setBusy] = useState(null);
  const [instruction, setInstruction] = useState('');
  const [regenLog, setRegenLog] = useState(null);

  const tailored = packet.resume_version;
  const base = packet.base_resume;
  const manifest = tailored?.render_manifest || {};
  const lines = manifest.lines || [];
  const validator = manifest.validator_result;
  const outcome = manifest.outcome;
  const refusal = manifest.refusal;

  const act = async (lineId, action) => {
    setBusy(`${lineId}:${action}`);
    try {
      await api.post(`/api/v1/applications/${packet.application.id}/resume-lines/${lineId}`,
        { action },
        withIdempotency(),
      );
      await onReload();
    } finally { setBusy(null); }
  };

  const regenerate = async () => {
    setBusy('regen');
    setRegenLog(null);
    try {
      const { data } = await api.post(`/api/v1/applications/${packet.application.id}/regenerate`,
        { instruction: instruction.trim() || null },
        withIdempotency(),
      );
      setRegenLog({
        outcome: data.outcome,
        refusal: data.refusal,
        n_lines: data.resume_version?.render_manifest?.lines?.length || 0,
      });
      setInstruction('');
      await onReload();
    } catch (e) {
      setRegenLog({ outcome: 'error', error: e?.response?.data?.detail?.error || 'unknown' });
    } finally { setBusy(null); }
  };

  const exportUrl = (fmt) => `/api/v1/applications/${packet.application.id}/export/${fmt}`;
  const downloadExport = async (fmt) => {
    setBusy(`export:${fmt}`);
    try {
      const res = await api.get(exportUrl(fmt), { responseType: 'blob' });
      const blob = new Blob([res.data], { type: res.headers['content-type'] });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `tailored-${packet.application.id}.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
    } finally { setBusy(null); }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Grounded regeneration"
          subtitle="Instructions are checked against your APPROVED claims. Requests to include facts we don't have are refused with an explanation — never silently fabricated."
        />
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <Input
              label="Instruction to the tailoring engine (optional)"
              placeholder='e.g., "Emphasize simulation work" or "Add my PMP certification"'
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              data-testid="regenerate-instruction-input"
            />
          </div>
          <Button variant="accent" onClick={regenerate} loading={busy === 'regen'} data-testid="regenerate-btn">
            <RefreshCw className="h-4 w-4" /> Regenerate
          </Button>
        </div>
        {regenLog && (
          <div
            className={`mt-3 rounded-md border p-3 text-xs ${
              regenLog.refusal ? 'border-red-500/40 bg-red-500/5' :
              regenLog.outcome === 'passed' ? 'border-accent/40 bg-accent/5' :
              'border-amber-500/40 bg-amber-500/5'
            }`}
            data-testid="regenerate-log"
          >
            {regenLog.refusal ? (
              <>
                <div className="flex items-center gap-2 font-medium text-red-700 dark:text-red-400">
                  <Ban className="h-3.5 w-3.5" /> Instruction refused
                </div>
                <p className="mt-1">{regenLog.refusal.message}</p>
                <p className="mt-1 muted font-mono">reason: {regenLog.refusal.reason}</p>
              </>
            ) : (
              <>Outcome: <span className="font-mono">{regenLog.outcome}</span> · new manifest has {regenLog.n_lines} lines.</>
            )}
          </div>
        )}
      </Card>

      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <CardHeader
            title="Base résumé"
            subtitle="Deterministic bullets built directly from your approved claims. Nothing generated."
          />
          <div className="space-y-2 text-sm">
            {(base?.render_manifest?.lines || []).map((L) => (
              <div key={L.line_id} className="rounded-md border border-line dark:border-line-dark p-3">
                <p className="leading-relaxed">{L.text}</p>
                <div className="text-[10px] muted font-mono mt-1">claims: {L.claim_ids?.map((id) => id.slice(0, 6)).join(', ') || '—'}</div>
              </div>
            ))}
            {(base?.render_manifest?.lines || []).length === 0 && <p className="muted text-sm">No base yet.</p>}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Tailored résumé"
            subtitle={
              <span>Every line is <strong>grounded</strong> in an approved claim and vetted by the validator. Accept the ones you want.</span>
            }
            action={<div className="flex items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => downloadExport('pdf')} loading={busy === 'export:pdf'} data-testid="export-pdf-btn"><Download className="h-3 w-3" /> PDF</Button>
              <Button size="sm" variant="secondary" onClick={() => downloadExport('docx')} loading={busy === 'export:docx'} data-testid="export-docx-btn"><Download className="h-3 w-3" /> DOCX</Button>
            </div>}
          />
          <div className="space-y-2 text-sm">
            {lines.map((L) => (
              <LineRow key={L.line_id} line={L} onAccept={(id) => act(id, 'accept')} onRevert={(id) => act(id, 'revert')} busy={busy} />
            ))}
            {lines.length === 0 && <p className="muted text-sm">No tailored lines yet — click Regenerate above.</p>}
          </div>
          {(validator?.rejected_lines || []).length > 0 && (
            <div className="mt-3 rounded-md border border-red-500/40 bg-red-500/5 p-3 text-xs">
              <div className="font-medium text-red-700 dark:text-red-400 mb-1">Rejected by the validator ({validator.rejected_lines.length})</div>
              <ul className="space-y-1">
                {validator.rejected_lines.slice(0, 5).map((r, i) => (
                  <li key={i}>
                    <span className="italic">"{r.text.slice(0, 80)}…"</span> — reasons: {r.reasons.map(rlabel).join(', ')}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function ScreenerRow({ q, onSave, busy }) {
  const [answer, setAnswer] = useState(q.answer || '');
  const [approved, setApproved] = useState(!!q.approved);
  const [autoBusy, setAutoBusy] = useState(false);
  const isSensitive = q.sensitive;
  const isStatic = q.static_only;
  const dirty = (answer !== (q.answer || '')) || (approved !== !!q.approved);

  const generate = async () => {
    setAutoBusy(true);
    try {
      const { data } = await api.post(
        `/api/v1/applications/${q.applicationId}/screeners/${encodeURIComponent(q.question_id)}/generate`,
        {},
        withIdempotency(),
      );
      if (data.generated_answer) setAnswer(data.generated_answer);
    } finally { setAutoBusy(false); }
  };

  const save = () => onSave(q.question_id, { answer, approved });

  if (isStatic) {
    return (
      <div className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-900 p-4" data-testid={`screener-${q.question_id}-static`}>
        <div className="flex items-start gap-2">
          <HelpCircle className="h-4 w-4 muted flex-shrink-0 mt-0.5" />
          <div>
            <div className="text-xs muted uppercase tracking-wide">Static · never stored</div>
            <p className="text-sm mt-1 leading-relaxed">{q.text}</p>
          </div>
        </div>
      </div>
    );
  }

  const wrapCls = isSensitive
    ? 'rounded-md border border-amber-500/40 bg-amber-500/5 p-4'
    : 'rounded-md border border-line dark:border-line-dark p-4';

  return (
    <div className={wrapCls} data-testid={`screener-${q.question_id}`}>
      <div className="flex items-start justify-between gap-2 mb-2">
        <p className="text-sm font-medium">{q.text}</p>
        {isSensitive && (
          <span className="pill border-amber-500/40 text-amber-700 dark:text-amber-400 flex-shrink-0" data-testid={`screener-${q.question_id}-sensitive-badge`}>
            <AlertTriangle className="h-3 w-3" /> sensitive · never AI-generated
          </span>
        )}
      </div>
      <textarea
        className="w-full rounded-md border border-line dark:border-line-dark bg-white dark:bg-neutral-900 p-2 text-sm"
        rows={3}
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        placeholder={isSensitive ? "Type your answer — visa/salary/clearance responses are never AI-generated." : "Your answer"}
        data-testid={`screener-${q.question_id}-input`}
      />
      <div className="flex items-center justify-between mt-2 gap-2 flex-wrap">
        <div className="text-xs muted">
          provenance: {q.provenance || '—'}
          {isSensitive && ' · requires explicit approval per application'}
        </div>
        <div className="flex items-center gap-2">
          {!isSensitive && (
            <Button size="sm" variant="ghost" onClick={generate} loading={autoBusy} data-testid={`screener-${q.question_id}-generate`}>
              <Sparkles className="h-3 w-3" /> Suggest grounded
            </Button>
          )}
          {isSensitive && (
            <label className="text-xs flex items-center gap-1 muted">
              <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} data-testid={`screener-${q.question_id}-approve`} />
              Approved for this application
            </label>
          )}
          <Button size="sm" variant="accent" onClick={save} loading={busy === q.question_id} disabled={!dirty} data-testid={`screener-${q.question_id}-save`}>
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}

function ScreenersTab({ packet, onReload }) {
  const [busy, setBusy] = useState(null);
  const questions = (packet.screeners_view?.questions || []).map((q) => ({ ...q, applicationId: packet.application.id }));

  const save = async (qid, payload) => {
    setBusy(qid);
    try {
      await api.post(
        `/api/v1/applications/${packet.application.id}/screeners/${encodeURIComponent(qid)}/answer`,
        { ...payload, provenance: 'user' },
        withIdempotency(),
      );
      await onReload();
    } finally { setBusy(null); }
  };

  return (
    <div className="space-y-3">
      {questions.map((q) => <ScreenerRow key={q.question_id} q={q} onSave={save} busy={busy} />)}
    </div>
  );
}

function SummaryTab({ packet, onReadyForApproval, submitBusy }) {
  const app = packet.application;
  const validator = packet.resume_version?.render_manifest?.validator_result;
  const nSensitiveOpen = (packet.screeners_view?.questions || []).filter((q) => q.sensitive && !q.approved).length;
  const canGo = app.state === 'preparing' && nSensitiveOpen === 0 && !!validator;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Packet overview" subtitle="Everything the packet knows before you send it to awaiting_approval." />
        <dl className="grid grid-cols-2 gap-y-2 text-sm">
          <dt className="muted">Job</dt><dd>{app.job_snapshot?.title} @ {app.job_snapshot?.company_name}</dd>
          <dt className="muted">Route</dt><dd className="font-mono">{app.route}</dd>
          <dt className="muted">State</dt><dd className="font-mono" data-testid="summary-state">{app.state}</dd>
          <dt className="muted">Tailored résumé</dt><dd>{packet.resume_version ? '✓ present' : '— none'}</dd>
          <dt className="muted">Validator</dt><dd><ValidatorChip result={validator} outcome={packet.resume_version?.render_manifest?.outcome} /></dd>
          <dt className="muted">Sensitive screeners open</dt><dd data-testid="summary-sensitive-open">{nSensitiveOpen}</dd>
          <dt className="muted">Route rationale</dt><dd className="text-xs muted leading-relaxed">{app.route_rationale}</dd>
        </dl>
      </Card>
      <div className="flex items-center gap-3">
        <Button variant="accent" onClick={onReadyForApproval} loading={submitBusy} disabled={!canGo} data-testid="ready-for-approval-btn">
          <Send className="h-4 w-4" /> Ready for approval
        </Button>
        {!canGo && app.state === 'preparing' && (
          <p className="text-xs muted">Fill and approve every sensitive screener first.</p>
        )}
        {app.state === 'awaiting_approval' && (
          <p className="text-xs text-accent">Packet is awaiting your final approval. Phase 5 wires the actual send path.</p>
        )}
      </div>
    </div>
  );
}

export default function ApplicationPrepPage() {
  const { applicationId } = useParams();
  const nav = useNavigate();
  const [packet, setPacket] = useState(null);
  const [screenersView, setScreenersView] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('resume');
  const [submitBusy, setSubmitBusy] = useState(false);
  const [prepBusy, setPrepBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [{ data: p }, { data: s }] = await Promise.all([
        api.get(`/api/v1/applications/${applicationId}/prep`),
        api.get(`/api/v1/applications/${applicationId}/screeners`),
      ]);
      setPacket({ ...p, screeners_view: s });
      setScreenersView(s);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') setError('generate_materials consent is required to prepare an application.');
      else if (detail === 'application_not_found') setError('Application not found.');
      else setError('Could not load application.');
    }
  }, [applicationId]);
  useEffect(() => { load(); }, [load]);

  const triggerPrepare = async () => {
    setPrepBusy(true);
    try {
      await api.post(`/api/v1/applications/${applicationId}/prepare`, {}, withIdempotency());
      await load();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') setError('generate_materials consent is required.');
      else setError('Prepare failed.');
    } finally { setPrepBusy(false); }
  };

  const ready = async () => {
    setSubmitBusy(true);
    try {
      await api.post(`/api/v1/applications/${applicationId}/ready-for-approval`, {}, withIdempotency());
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (d?.error === 'sensitive_screener_gate') alert(d.message);
      else if (d?.error === 'state_precondition_failed') alert('State changed elsewhere.');
      else alert('Ready-for-approval failed.');
    } finally { setSubmitBusy(false); }
  };

  if (error) return (
    <div className="max-w-3xl mx-auto space-y-4">
      <ErrorBlock message={error} onRetry={load} />
      <Link to="/applications" className="text-sm underline muted"><ArrowLeft className="h-3 w-3 inline" /> Back to applications</Link>
    </div>
  );
  if (!packet) return <div className="max-w-3xl mx-auto"><LoadingBlock label="Loading prep packet…" /></div>;

  const app = packet.application;
  const validator = packet.resume_version?.render_manifest?.validator_result;
  const isSample = !!app.job_snapshot?.is_sample;
  const needsPrepare = app.state === 'shortlisted' || !packet.resume_version;

  return (
    <div className="max-w-6xl mx-auto space-y-6 animate-fadeIn" data-testid="application-prep-page">
      <div>
        <button type="button" onClick={() => nav('/applications')} className="text-xs muted underline flex items-center gap-1 mb-2"><ArrowLeft className="h-3 w-3" /> Back to Applications</button>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-semibold flex items-center gap-2 flex-wrap">
              <FileText className="h-5 w-5" /> {app.job_snapshot?.title}
              {isSample && (
                <span className="pill pill-neutral !bg-amber-500/10 !border-amber-500/30 !text-amber-700 dark:!text-amber-400 font-medium" data-testid="sample-badge">
                  <TestTube2 className="h-3 w-3" /> SAMPLE
                </span>
              )}
            </h1>
            <p className="muted text-sm mt-1">
              {app.job_snapshot?.company_name} · state <span className="font-mono">{app.state}</span> · route <span className="font-mono">{app.route}</span>
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <ValidatorChip
              result={validator}
              outcome={packet.resume_version?.render_manifest?.outcome}
              refusal={packet.resume_version?.render_manifest?.refusal}
            />
          </div>
        </div>
      </div>

      {needsPrepare && (
        <Card>
          <CardHeader
            title="Prepare this application"
            subtitle="We tailor your résumé using ONLY your approved Career Passport claims. Validator will reject any AI line that references facts you don't actually have."
          />
          <Button variant="accent" onClick={triggerPrepare} loading={prepBusy} data-testid="prepare-btn">
            <Sparkles className="h-4 w-4" /> Prepare packet
          </Button>
        </Card>
      )}

      {!needsPrepare && (
        <>
          <div className="flex items-center gap-1 border-b border-line dark:border-line-dark">
            {['resume', 'screeners', 'summary'].map((k) => (
              <button
                type="button"
                key={k}
                className={`px-4 py-2 text-sm border-b-2 -mb-px ${
                  tab === k
                    ? 'border-accent text-accent font-medium'
                    : 'border-transparent muted hover:text-ink dark:hover:text-ink-dark'
                }`}
                onClick={() => setTab(k)}
                data-testid={`prep-tab-${k}`}
              >
                {k[0].toUpperCase() + k.slice(1)}
              </button>
            ))}
          </div>

          {tab === 'resume' && <ResumeDiffTab packet={packet} onReload={load} />}
          {tab === 'screeners' && <ScreenersTab packet={packet} onReload={load} />}
          {tab === 'summary' && <SummaryTab packet={packet} onReadyForApproval={ready} submitBusy={submitBusy} />}
        </>
      )}
    </div>
  );
}
