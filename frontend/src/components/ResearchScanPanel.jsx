import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { ResearchScanError, newScanRequestKey, prepareScanInput, validateScanCapabilities, validateScanList, validateScanResponse, validateScanStart, parseScanReport, describeScanFailure, isScanActive, canCancelScan, canResumeScan, canImportScan, SCAN_POLL_INTERVAL_MS, SCAN_MAX_POLLS } from '../lib/researchScans';

const endpoint = '/api/v1/collider/scans';
const inputClass = 'w-full rounded-xl border border-line dark:border-line-dark bg-white/60 dark:bg-black/20 px-3 py-2 text-sm';
const label = value => value.replace(/_/g, ' ');

export default function ResearchScanPanel({ onImportReport, onBusy, resetKey }) {
  const [capabilities, setCapabilities] = useState(null);
  const [urls, setUrls] = useState(''), [query, setQuery] = useState('');
  const [pageLimit, setPageLimit] = useState('5'), [followLinks, setFollowLinks] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [runs, setRuns] = useState([]), [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(null), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [uncertainStart, setUncertainStart] = useState(false), [confirmDifferent, setConfirmDifferent] = useState(false);
  const [pollingStopped, setPollingStopped] = useState(false);
  const mounted = useRef(true), sequence = useRef(0), request = useRef(null), attempt = useRef(null), pollCount = useRef(0);
  const latestReset = useRef(resetKey), reportCallback = useRef(onImportReport), busyCallback = useRef(onBusy), pollLoad = useRef(null);
  latestReset.current = resetKey; reportCallback.current = onImportReport; busyCallback.current = onBusy;

  const cancelLocal = useCallback(() => {
    ++sequence.current;
    const active = request.current; request.current = null;
    active?.controller.abort();
    if (mounted.current) {
      setBusy(null);
      if (active?.kind === 'start' && attempt.current) { attempt.current.uncertain = true; setUncertainStart(true); }
    }
    if (active?.kind === 'report') busyCallback.current?.(false);
  }, []);
  function begin(kind, id = '') {
    cancelLocal(); setError(''); setNotice('');
    const active = { kind, id, controller: new AbortController(), version: ++sequence.current, reset: latestReset.current };
    request.current = active; setBusy(kind);
    if (kind === 'report') busyCallback.current?.(true);
    return active;
  }
  function current(active) {
    return mounted.current && active.version === sequence.current && !active.controller.signal.aborted && (active.kind !== 'report' || active.reset === latestReset.current);
  }
  function finish(active) {
    if (!current(active)) return;
    request.current = null; setBusy(null);
    if (active.kind === 'report') busyCallback.current?.(false);
  }
  function acceptRun(run) {
    setSelected(run);
    setRuns(previous => [run, ...previous.filter(item => item.id !== run.id)].slice(0, 100));
  }
  function failure(active, problem) {
    if (!current(active)) return;
    const description = describeScanFailure(problem, active.kind);
    if (description.sessionExpired) {
      cancelLocal(); attempt.current = null; pollCount.current = 0;
      setRuns([]); setSelected(null); setCapabilities(null); setUrls(''); setQuery(''); setAcknowledged(false);
      setUncertainStart(false); setConfirmDifferent(false); setPollingStopped(true); setNotice('');
    } else {
      if (active.kind === 'start' && description.uncertain && attempt.current) { attempt.current.uncertain = true; setUncertainStart(true); }
      if (['status', 'cancel', 'resume'].includes(active.kind)) setPollingStopped(true);
    }
    setError(description.message);
  }

  async function checkCapabilities() {
    const active = begin('capabilities');
    try {
      const response = await api.get(`${endpoint}/capabilities`, { signal: active.controller.signal, timeout: 15000 });
      if (current(active)) setCapabilities(validateScanCapabilities(response?.data));
    } catch (problem) { if (current(active)) setCapabilities(null); failure(active, problem); }
    finally { finish(active); }
  }
  const initialCheck = useRef(checkCapabilities);
  useEffect(() => {
    mounted.current = true; initialCheck.current();
    return () => { mounted.current = false; cancelLocal(); };
  }, [cancelLocal]);
  useEffect(() => {
    // Other Research imports invalidate only a pending report transfer, not the
    // server run or its uncertain start key.
    if (request.current?.kind === 'report') { cancelLocal(); setError(''); setNotice(''); }
  }, [resetKey, cancelLocal]);

  async function refreshList() {
    if (!capabilities?.available) return;
    const active = begin('list');
    try {
      const response = await api.get(endpoint, { signal: active.controller.signal, timeout: 15000 });
      if (current(active)) { setRuns(validateScanList(response?.data)); setNotice('Saved scan list refreshed. No research report was opened.'); }
    } catch (problem) { failure(active, problem); }
    finally { finish(active); }
  }
  async function loadRun(id, automatic = false) {
    if (!capabilities?.available) return;
    if (!automatic) { pollCount.current = 0; setPollingStopped(false); }
    const active = begin('status', id);
    try {
      const response = await api.get(`${endpoint}/${id}`, { signal: active.controller.signal, timeout: 15000 });
      if (current(active)) acceptRun(validateScanResponse(response?.data, id));
    } catch (problem) { failure(active, problem); }
    finally { finish(active); }
  }
  pollLoad.current = loadRun;
  useEffect(() => {
    if (!capabilities?.available || !isScanActive(selected) || busy || pollingStopped) return undefined;
    if (pollCount.current >= SCAN_MAX_POLLS) { setPollingStopped(true); return undefined; }
    const timer = window.setTimeout(() => { ++pollCount.current; pollLoad.current(selected.id, true); }, SCAN_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [capabilities, selected, busy, pollingStopped]);

  async function start(event) {
    event.preventDefault();
    if (!capabilities?.available || !acknowledged || request.current?.kind === 'start') return;
    let input;
    try { input = prepareScanInput({ urls, query, pageLimit, followLinks }); }
    catch (problem) { setError(describeScanFailure(problem).message); return; }
    const fingerprint = JSON.stringify(input);
    if (attempt.current?.uncertain && attempt.current.fingerprint !== fingerprint) {
      setError('Resolve the unconfirmed request before changing its inputs.'); return;
    }
    if (!attempt.current || attempt.current.fingerprint !== fingerprint) {
      let key;
      try { key = newScanRequestKey(); } catch (problem) { setError(describeScanFailure(problem).message); return; }
      if (typeof key !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(key)) { setError('A safe scan request key could not be created. Reload before retrying.'); return; }
      attempt.current = { key, fingerprint, input, uncertain: false };
    }
    const active = begin('start');
    try {
      const response = await api.post(endpoint, { input: attempt.current.input, confirm_storage: true }, { signal: active.controller.signal, timeout: 20000, headers: { 'Idempotency-Key': attempt.current.key } });
      if (!current(active)) return;
      const receipt = validateScanStart(response?.data);
      attempt.current.uncertain = false; setUncertainStart(false); setConfirmDifferent(false); setAcknowledged(false);
      pollCount.current = 0; setPollingStopped(false); acceptRun(receipt.run);
      setNotice(receipt.replay ? 'The existing scan request was recovered. No duplicate start is being claimed.' : 'Scan request accepted. This is not a completed collection or a coverage guarantee.');
    } catch (problem) { failure(active, problem); }
    finally { finish(active); }
  }
  async function changeRun(action) {
    if (!capabilities?.available || !selected || (action === 'cancel' ? !canCancelScan(selected) : !canResumeScan(selected))) return;
    const id = selected.id, active = begin(action, id);
    try {
      const response = await api.post(`${endpoint}/${id}/${action}`, {}, { signal: active.controller.signal, timeout: 15000 });
      if (current(active)) {
        acceptRun(validateScanResponse(response?.data, id)); pollCount.current = 0; setPollingStopped(false);
        setNotice(action === 'cancel' ? 'Cancellation requested. Check the returned status; in-flight source work may already have completed.' : 'Resume requested. Failed or uncertain reads are not automatically retried.');
      }
    } catch (problem) { failure(active, problem); }
    finally { finish(active); }
  }
  async function importReport() {
    if (!capabilities?.available || !canImportScan(selected)) return;
    const id = selected.id, active = begin('report', id);
    try {
      const response = await api.get(`${endpoint}/${id}/report`, { signal: active.controller.signal, timeout: 35000 });
      if (!current(active)) return;
      const report = parseScanReport(response?.data, id);
      if (current(active)) {
        if (typeof reportCallback.current !== 'function') throw new ResearchScanError('SCAN_INVALID_RESPONSE', 'The research workspace is not ready to receive this report.');
        reportCallback.current(report);
        setNotice('Retained scan evidence opened in Research. Completeness and claims are not independently verified.');
      }
    } catch (problem) { failure(active, problem); }
    finally { finish(active); }
  }
  function edit(setter, value) {
    if (uncertainStart || busy === 'start') return;
    setter(value); setAcknowledged(false); setError('');
  }
  function useDifferentInputs() {
    if (request.current?.kind === 'start') return;
    attempt.current = null; setUncertainStart(false); setConfirmDifferent(false); setAcknowledged(false);
    setNotice('The previous request may still be running. Check saved scans before starting another.');
  }
  const locked = uncertainStart || busy === 'start';

  return <section className="liquid-card p-5 space-y-4" aria-labelledby="research-scan-heading" data-testid="research-scan-panel">
    <div><h2 id="research-scan-heading" className="text-lg font-semibold">Scan selected sources</h2><p className="text-sm muted mt-2">Discover and collect bounded public-web evidence through LYNK Collider. Source permissions, availability, quotas and page limits still apply. This does not scan the whole internet or apply for jobs.</p></div>
    <div className="rounded-xl border border-line dark:border-line-dark p-3 text-sm" role="note">
      {capabilities?.available ? 'Scanning is configured. This does not establish that the engine or any source is healthy.' : capabilities?.reason === 'disabled' ? 'Scanning is disabled for this deployment.' : capabilities?.reason === 'configuration_required' ? 'Scanning needs server configuration before it can start.' : 'Scan availability has not been confirmed.'}
      <button type="button" className="liquid-capsule liquid-secondary mt-2" disabled={busy === 'capabilities'} onClick={checkCapabilities}>{busy === 'capabilities' ? 'Checking availability…' : 'Check availability'}</button>
    </div>
    <form onSubmit={start} className="space-y-3">
      <label className="block text-xs muted space-y-1"><span>Search query</span><input className={inputClass} maxLength={400} value={query} disabled={locked} onChange={event => edit(setQuery, event.target.value)} placeholder="A focused question or opportunity" /></label>
      <label className="block text-xs muted space-y-1"><span>Source URLs · one per line, up to 20</span><textarea className={`${inputClass} min-h-24`} maxLength={42000} value={urls} disabled={locked} onChange={event => edit(setUrls, event.target.value)} placeholder="https://example.org/research" /></label>
      <details><summary className="cursor-pointer text-sm">Scan limits and advanced options</summary><div className="mt-3 space-y-3"><label className="block text-xs muted space-y-1"><span>Maximum pages</span><input type="number" min="1" max="20" step="1" className={inputClass} value={pageLimit} disabled={locked} onChange={event => edit(setPageLimit, event.target.value)} /></label><label className="flex gap-2 text-sm"><input type="checkbox" checked={followLinks} disabled={locked} onChange={event => edit(setFollowLinks, event.target.checked)} /><span>Follow same-origin links one level deep, within the same page limit</span></label></div></details>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={acknowledged} disabled={busy === 'start'} onChange={event => setAcknowledged(event.target.checked)} /><span>I understand source content from this scan will be stored in my Fynd account</span></label>
      <div className="flex flex-wrap gap-2"><button type="submit" className="liquid-capsule liquid-primary" disabled={!capabilities?.available || !acknowledged || busy === 'start'}>{busy === 'start' ? 'Starting scan…' : uncertainStart ? 'Retry same scan request' : 'Start scan'}</button><button type="button" className="liquid-capsule liquid-secondary" disabled={!capabilities?.available || busy === 'list'} onClick={refreshList}>{busy === 'list' ? 'Refreshing scans…' : 'Refresh saved scans'}</button></div>
    </form>
    {uncertainStart && <div className="rounded-xl border border-amber-400 p-3 space-y-2 text-sm"><p>The last start is unconfirmed and may already be running. Retrying keeps the same request key. Inputs stay locked until you explicitly choose to change them.</p>{!confirmDifferent ? <button className="liquid-capsule liquid-secondary" type="button" disabled={busy === 'start'} onClick={() => setConfirmDifferent(true)}>Use different inputs</button> : <><p>A new request can create another scan while the previous one continues.</p><button className="liquid-capsule liquid-secondary" type="button" disabled={busy === 'start'} onClick={useDifferentInputs}>Continue with different inputs</button><button className="liquid-capsule liquid-secondary" type="button" disabled={busy === 'start'} onClick={() => setConfirmDifferent(false)}>Keep original request</button></>}</div>}
    {error && <p role="alert" className="rounded-xl border border-red-400 p-3 text-sm">{error}</p>}
    {notice && <p role="status" className="text-sm muted">{notice}</p>}
    {!!runs.length && <details open><summary className="cursor-pointer text-sm">Saved scans ({runs.length})</summary><ul className="mt-3 space-y-2 max-h-64 overflow-auto">{runs.map(run => <li key={run.id}><button type="button" className="text-left w-full rounded-xl border border-line dark:border-line-dark p-3" onClick={() => loadRun(run.id)} disabled={!capabilities?.available} aria-label={`View scan ${run.id}`}><span className="block text-sm break-words">{run.input.query || run.input.urls[0] || 'Stored source scan'}</span><span className="text-xs muted">{label(run.status)} · {run.createdAt}</span></button></li>)}</ul></details>}
    {selected && <div className="rounded-xl border border-line dark:border-line-dark p-4 space-y-3" data-testid="selected-scan">
      <h3 className="font-medium">Scan status: {label(selected.status)}</h3><p className="text-xs muted break-all">Scan {selected.id}</p>
      <p className="text-sm">{selected.progress.done} of {selected.progress.total} recorded steps settled</p><p className="text-xs muted">Retained pages: {selected.result.counts.savedPages} · jobs: {selected.result.counts.savedJobs} · structured records: {selected.result.counts.structuredRecords}</p>
      <p className="text-xs muted">These are run counts, not internet coverage or proof that evidence is complete. {selected.result.incomplete ? 'This run is marked incomplete.' : 'Completed steps do not verify source claims.'}</p>
      <div className="flex flex-wrap gap-2"><button className="liquid-capsule liquid-secondary" type="button" disabled={!capabilities?.available || busy === 'status'} onClick={() => loadRun(selected.id)}>Refresh scan status</button>{canCancelScan(selected) && <button className="liquid-capsule liquid-secondary" type="button" disabled={!capabilities?.available || busy === 'cancel'} onClick={() => changeRun('cancel')}>Cancel scan</button>}{canResumeScan(selected) && <button className="liquid-capsule liquid-secondary" type="button" disabled={!capabilities?.available || busy === 'resume'} onClick={() => changeRun('resume')}>Resume scan</button>}{canImportScan(selected) && <button className="liquid-capsule liquid-primary" type="button" disabled={!capabilities?.available || busy === 'report'} onClick={importReport}>{busy === 'report' ? 'Opening scan report…' : 'Open retained report'}</button>}</div>
      {isScanActive(selected) && <p className="text-xs muted">{pollingStopped ? 'Automatic status checks are paused. Use Refresh scan status to continue checking.' : 'Status checks run at least 5 seconds apart and stop after 60 checks or any error.'}</p>}
    </div>}
    <p className="text-xs muted">Unchanged inputs recover the same scan request. Change inputs to create a different scan. Leaving or refreshing this page does not cancel server work. If a start or cancellation is unconfirmed, check saved scans before retrying. Scanning stores source evidence; opening a report does not submit job applications.</p>
  </section>;
}
