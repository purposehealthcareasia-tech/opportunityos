import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { api } from '../lib/api';
import { buildReport } from '../lib/researchReport';

const UUID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const UUID_RE = new RegExp(`^${UUID}$`, 'i');
const JOB_PATH_RE = new RegExp(`^/jobs/(${UUID})/?$`, 'i');
const INPUT_ERROR = 'Enter a Fynd job UUID or an internal /jobs/UUID path. External job links are not supported here.';
const inputClass = 'w-full rounded-xl border border-line dark:border-line-dark bg-white/60 dark:bg-black/20 px-3 py-2 text-sm';
// eslint-disable-next-line no-control-regex -- Intentionally remove non-printing ASCII controls from imported source labels.
const clean = (value, max) => typeof value === 'string' ? value.replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, max) : '';
const storedDate = value => typeof value === 'string' && /^\d{4}-\d\d-\d\d/.test(value) && value.length <= 40 && Number.isFinite(Date.parse(value)) ? value : '';
class ImportProblem extends Error {}

function prefill(search) {
  const values = new URLSearchParams(search).getAll('job');
  if (!values.length) return { value: '', error: '' };
  if (values.length !== 1 || !UUID_RE.test(values[0])) return { value: '', error: 'The research link has an invalid Fynd job ID. Enter a valid job UUID below.' };
  return { value: values[0].toLowerCase(), error: '' };
}

function jobReport(job, expectedId) {
  if (!job || typeof job !== 'object' || Array.isArray(job) || typeof job.id !== 'string' || !UUID_RE.test(job.id) || job.id.toLowerCase() !== expectedId) {
    throw new ImportProblem('Fynd returned a different or invalid job record. Nothing was imported.');
  }
  if (job.is_sample === true) throw new ImportProblem('Sample jobs cannot be imported as research evidence. Choose a non-sample Fynd job.');
  if (job.is_sample !== false) throw new ImportProblem('This stored job does not declare whether it is a sample. Nothing was imported.');
  if (job.needs_origin === true || typeof job.origin_url !== 'string' || !job.origin_url.trim()) throw new ImportProblem('This job has no usable original source. The application link will not be substituted.');
  if (job.jd_text != null && typeof job.jd_text !== 'string') throw new ImportProblem('The stored job description has an unsupported format. Nothing was imported.');
  const body = job.jd_text || '';
  if (body.length > 60000 || new Blob([body]).size > 250000) throw new ImportProblem('The stored description is too large for this bounded import. Use a smaller evidence export.');
  const title = clean(job.title, 500) || 'Stored Fynd job', company = clean(job.company_name, 300);
  const verified = storedDate(job.last_verified), status = clean(job.status, 80);
  try {
    return buildReport({
      title: company ? `${company} — ${title}` : title,
      records: [{ id: job.id.toLowerCase(), url: job.origin_url, title: company ? `${title} · ${company}` : title,
        kind: 'jobs', source: clean(job.source, 200) || 'Fynd stored job', content: body,
        contentStatus: body.trim() ? 'unknown' : 'metadata-only', publishedAt: storedDate(job.posted_at) }],
      omissions: [
        'Imported one existing Fynd job observation through the signed-in job-detail API; the original website was not fetched.',
        'Stored descriptions and source metadata may be incomplete or stale. This import does not verify freshness, availability, or completeness.',
        'Personal match scores, eligibility gates, skill gaps and the separate application-link field were not copied. The original source URL is retained. No application was prepared or submitted.',
      ],
      warnings: [
        ...(status ? [`Stored Fynd status: ${status}. This status was not rechecked against the source.`] : []),
        ...(verified ? [`Last verification timestamp supplied by Fynd: ${verified}. No new verification was performed here.`] : []),
      ],
    });
  } catch {
    throw new ImportProblem('The original source URL or stored evidence is unsafe or unsupported. Nothing was imported.');
  }
}

function friendlyError(error) {
  if (error instanceof ImportProblem) return error.message;
  const status = error?.response?.status;
  if (status === 401) return 'Your Fynd session has expired. Sign in again, then retry this import.';
  if (status === 403) return 'Fynd did not authorize this job read. Review your account permissions and required career-data consent, then retry.';
  if (status === 404) return 'That Fynd job could not be found. Check the job ID or open another job.';
  if (['ECONNABORTED', 'ETIMEDOUT'].includes(error?.code)) return 'Fynd took too long to respond. Your report is unchanged; try again shortly.';
  if (status === 503) return 'Fynd job details are temporarily unavailable. Your report is unchanged; try again shortly.';
  return 'The stored Fynd job could not be loaded. Your report is unchanged; try again shortly.';
}

// resetKey is an optional parent-controlled cancellation token for Clear/replace.
// No automatic fetch, local storage, external URL request, or application action.
export default function FyndJobResearchImport({ onReport, onBusy, resetKey }) {
  const location = useLocation();
  const initial = prefill(location.search);
  const [value, setValue] = useState(initial.value);
  const [error, setError] = useState(initial.error);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true), request = useRef(null), sequence = useRef(0), lastReset = useRef(resetKey);
  const busyCallback = useRef(onBusy);
  busyCallback.current = onBusy;
  const cancel = useCallback(() => {
    ++sequence.current;
    request.current?.abort(); request.current = null;
    if (mounted.current) setBusy(false);
    busyCallback.current?.(false);
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; cancel(); };
  }, [cancel]);
  useEffect(() => {
    cancel();
    const next = prefill(location.search);
    setValue(next.value); setError(next.error); setNotice('');
  }, [location.search, cancel]);
  useEffect(() => {
    if (lastReset.current === resetKey) return;
    lastReset.current = resetKey;
    cancel(); setValue(''); setError(''); setNotice('');
  }, [resetKey, cancel]);

  async function load(event) {
    event.preventDefault();
    cancel(); setError(''); setNotice('');
    const text = value.trim(), id = UUID_RE.test(text) ? text.toLowerCase() : JOB_PATH_RE.exec(text)?.[1]?.toLowerCase();
    if (!id) { setError(INPUT_ERROR); return; }
    const controller = new AbortController(), version = ++sequence.current;
    request.current = controller; setBusy(true); busyCallback.current?.(true);
    try {
      const response = await api.get(`/api/v1/jobs/${encodeURIComponent(id)}`, { signal: controller.signal, timeout: 15000 });
      if (!mounted.current || version !== sequence.current || controller.signal.aborted) return;
      const report = jobReport(response?.data, id);
      if (!mounted.current || version !== sequence.current || controller.signal.aborted) return;
      onReport(report);
      setNotice('Stored Fynd job loaded. The original source was not fetched or reverified.');
    } catch (failure) {
      if (mounted.current && version === sequence.current && !controller.signal.aborted) setError(friendlyError(failure));
    } finally {
      if (mounted.current && version === sequence.current) { request.current = null; setBusy(false); busyCallback.current?.(false); }
    }
  }
  function clear() { cancel(); setValue(''); setError(''); setNotice(''); }

  return <section className="liquid-card p-5 space-y-4" aria-labelledby="fynd-job-import-heading" data-testid="fynd-job-research-import">
    <div><h2 id="fynd-job-import-heading" className="text-lg font-semibold">Research a Fynd job</h2><p className="text-sm muted mt-2">Load a job already stored in Fynd using your signed-in access. This reads Fynd’s saved observation, not the live employer website. Sample jobs are excluded.</p></div>
    <form onSubmit={load} className="space-y-3" aria-busy={busy}>
      <label className="block text-xs muted space-y-1"><span>Fynd job ID or internal path</span><input className={inputClass} value={value} maxLength={80} autoComplete="off" spellCheck={false} placeholder="Job UUID or /jobs/UUID" onChange={event => { cancel(); setValue(event.target.value); setError(''); setNotice(''); }} /></label>
      <div className="flex flex-wrap gap-2"><button type="submit" className="liquid-capsule liquid-primary" disabled={busy || !value.trim()}>{busy ? 'Loading stored job…' : 'Load Fynd job'}</button><button type="button" className="liquid-capsule liquid-secondary" onClick={clear} disabled={!value && !busy && !error && !notice}>Clear job input</button></div>
    </form>
    <p className="text-xs muted">A linked job ID is only prefilled—nothing loads until you choose Load Fynd job. Loading replaces the open research report; a failed load leaves it unchanged. No application action is taken.</p>
    {error && <p role="alert" className="rounded-xl border border-red-400 p-3 text-sm">{error}</p>}
    {notice && <p role="status" className="text-sm muted">{notice}</p>}
  </section>;
}
