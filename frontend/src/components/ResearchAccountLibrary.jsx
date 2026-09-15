import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { ResearchAccountError, accountSnapshot, reopenSavedSnapshot, validateAccountListing, validateSavedReceipt, validateDeleteReceipt } from '../lib/researchAccount';

const endpoint = '/api/v1/research/reports';
const sizeLabel = bytes => `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;

function friendlyError(error, operation) {
  if (error instanceof ResearchAccountError) return error.message;
  const status = error?.response?.status;
  if (status === 401) return 'Your Fynd session has expired. Sign in again, then retry.';
  if (status === 403) return 'Your account is not authorized for this action. Check your account permissions and required consent.';
  if (status === 404) return 'That saved report is unavailable. Choose Saved reports to refresh the list.';
  if (status === 413) return 'This report exceeds an account-storage limit. Keep it local and download a copy instead.';
  if (status === 429) return 'Too many account requests. Wait a moment, then retry.';
  if (status === 503) return 'Account report storage is temporarily unavailable. Try again shortly.';
  if (operation === 'save' || operation === 'delete') return 'The account change could not be confirmed. It may have completed; refresh Saved reports before retrying.';
  return 'The saved report could not be loaded. Your open report is unchanged. Try again shortly.';
}

// This component never persists automatically. Every network request follows a
// user action; all response data is validated before it reaches a report view.
export default function ResearchAccountLibrary({ report, onReport, onBusy, resetKey }) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [listing, setListing] = useState(null);
  const [confirmation, setConfirmation] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const mounted = useRef(true), sequence = useRef(0), request = useRef(null);
  const latestReport = useRef(report), latestReset = useRef(resetKey);
  const reportCallback = useRef(onReport), busyCallback = useRef(onBusy);
  latestReport.current = report; latestReset.current = resetKey;
  reportCallback.current = onReport; busyCallback.current = onBusy;

  const cancel = useCallback(() => {
    ++sequence.current;
    const active = request.current;
    request.current = null;
    active?.controller.abort();
    if (mounted.current) setBusy(null);
    if (active?.kind === 'load') busyCallback.current?.(false);
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; cancel(); };
  }, [cancel]);

  useEffect(() => {
    cancel(); setAcknowledged(false); setConfirmation(null); setError(''); setNotice('');
  }, [report, resetKey, cancel]);

  function begin(kind, id = '') {
    cancel(); setError(''); setNotice(''); setConfirmation(null);
    const active = { kind, id, controller: new AbortController(), version: ++sequence.current, report: latestReport.current, reset: latestReset.current };
    request.current = active; setBusy({ kind, id });
    if (kind === 'load') busyCallback.current?.(true);
    return active;
  }
  function current(active) {
    return mounted.current && sequence.current === active.version && !active.controller.signal.aborted &&
      latestReport.current === active.report && latestReset.current === active.reset;
  }
  function finish(active) {
    if (!current(active)) return;
    request.current = null; setBusy(null);
    if (active.kind === 'load') busyCallback.current?.(false);
  }
  function failure(active, problem) {
    if (current(active)) setError(friendlyError(problem, active.kind));
  }

  async function loadListing() {
    const active = begin('list');
    try {
      const response = await api.get(endpoint, { signal: active.controller.signal, timeout: 15000 });
      if (!current(active)) return;
      const next = validateAccountListing(response?.data);
      if (current(active)) { setListing(next); setNotice('Saved report list loaded. No evidence report was opened.'); }
    } catch (problem) { failure(active, problem); }
    finally { finish(active); }
  }

  async function save() {
    if (!report || !acknowledged) return;
    const active = begin('save');
    try {
      const bundle = accountSnapshot(active.report);
      const response = await api.post(endpoint, { bundle, confirm_storage: true }, { signal: active.controller.signal, timeout: 20000 });
      if (!current(active)) return;
      const receipt = validateSavedReceipt(response?.data);
      // byte_size is the server's bounded canonical size, which can differ from
      // browser JSON serialization (for example, Python 1.0 versus JS 1).
      if (receipt.report.title !== bundle.manifest.title) {
        throw new ResearchAccountError('ACCOUNT_INVALID_RESPONSE', 'Fynd returned inconsistent saved-report details. The save may have completed; refresh Saved reports before retrying.');
      }
      if (current(active)) {
        setAcknowledged(false); setListing(null);
        setNotice(receipt.replay ? 'This report snapshot is already saved in your Fynd account. Choose Saved reports to refresh the list.' : 'Report snapshot saved in your Fynd account. Choose Saved reports to refresh the list.');
      }
    } catch (problem) { failure(active, problem); }
    finally { finish(active); }
  }

  async function loadSaved(id) {
    const active = begin('load', id);
    try {
      const response = await api.get(`${endpoint}/${encodeURIComponent(id)}`, { signal: active.controller.signal, timeout: 20000 });
      if (!current(active)) return;
      const next = reopenSavedSnapshot(response?.data, id);
      if (current(active)) {
        reportCallback.current(next);
        setNotice('Saved snapshot opened. Its sources were not fetched or independently verified.');
      }
    } catch (problem) { failure(active, problem); }
    finally { finish(active); }
  }

  async function deleteSaved(id) {
    if (confirmation !== id) return;
    const active = begin('delete', id);
    try {
      const response = await api.delete(`${endpoint}/${encodeURIComponent(id)}`, { signal: active.controller.signal, timeout: 15000 });
      if (!current(active)) return;
      validateDeleteReceipt(response?.data);
      if (current(active)) {
        setListing(previous => previous ? {
          ...previous,
          reports: previous.reports.filter(item => item.id !== id),
          used_bytes: Math.max(0, previous.used_bytes - (previous.reports.find(item => item.id === id)?.byte_size || 0)),
        } : null);
        setNotice('Saved account copy deleted. Any report already open in this tab is unchanged.');
      }
    } catch (problem) { failure(active, problem); }
    finally { finish(active); }
  }

  return <section className="liquid-card p-5 space-y-4" aria-labelledby="research-account-heading" data-testid="research-account-library">
    <div><h2 id="research-account-heading" className="text-lg font-semibold">Your saved research</h2><p className="text-sm muted mt-2">Account storage is optional. Saving explicitly uploads a report snapshot to your private Fynd account; it does not crawl sources or independently verify imported claims.</p></div>
    <p className="text-xs muted">Limits: 8 MiB per report, 10 MiB total, and 20 saved reports. Larger reports stay local—download them before leaving.</p>
    <div className="space-y-3">
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={acknowledged} disabled={!report || busy?.kind === 'save'} onChange={event => setAcknowledged(event.target.checked)} /><span>I want to store this report in my Fynd account</span></label>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="liquid-capsule liquid-primary" disabled={!report || !acknowledged || busy?.kind === 'save'} onClick={save}>{busy?.kind === 'save' ? 'Saving report…' : 'Save report'}</button>
        <button type="button" className="liquid-capsule liquid-secondary" disabled={busy?.kind === 'list'} onClick={loadListing}>{busy?.kind === 'list' ? 'Loading saved list…' : 'Saved reports'}</button>
      </div>
    </div>
    <p className="text-xs muted">Nothing is saved or listed automatically. Opening a saved report replaces the current view only after validation; failed loads leave it unchanged. If a save or deletion is interrupted, it may still finish on the server. Refresh Saved reports to check.</p>
    {error && <p role="alert" className="rounded-xl border border-red-400 p-3 text-sm">{error}</p>}
    {notice && <p role="status" className="text-sm muted">{notice}</p>}
    {listing && <div className="space-y-3" aria-label="Saved report list">
      <p className="text-xs muted">{listing.reports.length} saved reports · {sizeLabel(listing.used_bytes)} account storage used</p>
      {listing.reports.length ? <ul className="space-y-3">{listing.reports.map(item => <li key={item.id} className="rounded-xl border border-line dark:border-line-dark p-3 space-y-2">
        <div><h3 className="font-medium text-sm break-words">{item.title || 'Untitled saved report'}</h3><p className="text-xs muted">{sizeLabel(item.byte_size)} · Saved {item.saved_at}</p></div>
        <div className="flex gap-2 flex-wrap">
          <button type="button" className="liquid-capsule liquid-secondary" aria-label={`Open saved report: ${item.title}`} disabled={busy?.kind === 'load' && busy.id === item.id} onClick={() => loadSaved(item.id)}>{busy?.kind === 'load' && busy.id === item.id ? 'Opening…' : 'Open saved report'}</button>
          <button type="button" className="liquid-capsule liquid-secondary" aria-label={`Delete saved report: ${item.title}`} disabled={busy?.kind === 'delete' && busy.id === item.id} onClick={() => { setConfirmation(item.id); setError(''); }}>{busy?.kind === 'delete' && busy.id === item.id ? 'Deleting…' : 'Delete account copy'}</button>
        </div>
        {confirmation === item.id && <div className="border-t border-line dark:border-line-dark pt-3 space-y-2"><p className="text-sm">Delete this saved account copy? Download a copy first if you want to keep it.</p><div className="flex gap-2 flex-wrap"><button type="button" className="liquid-capsule liquid-secondary" aria-label={`Confirm delete: ${item.title}`} onClick={() => deleteSaved(item.id)}>Confirm delete</button><button type="button" className="liquid-capsule liquid-secondary" onClick={() => setConfirmation(null)}>Keep saved report</button></div></div>}
      </li>)}</ul> : <p className="text-sm muted">No reports are saved in this account.</p>}
    </div>}
  </section>;
}
