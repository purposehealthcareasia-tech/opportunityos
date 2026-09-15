import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Upload, Download, Search, BookOpen, Link2, Building2, ListTree, ExternalLink, X } from 'lucide-react';
import { parseReport, filterRecords, buildDossier, exportReport, REPORT_KINDS, CONTENT_STATUSES } from '../lib/researchReport';
import FyndJobResearchImport from '../components/FyndJobResearchImport';
import ResearchAccountLibrary from '../components/ResearchAccountLibrary';
import ResearchScanPanel from '../components/ResearchScanPanel';

const label = value => String(value).replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]/g, ' ');
const tabs = [['evidence', 'Evidence', BookOpen], ['links', 'Research links', Link2], ['company', 'Company dossier', Building2], ['trace', 'Discovery trail', ListTree]];
const inputClass = 'w-full rounded-xl border border-line dark:border-line-dark bg-white/60 dark:bg-black/20 px-3 py-2 text-sm';
const sectionNames = { products: 'Products', docs: 'Documentation', announcements: 'Announcements', roadmap: 'Roadmap', otherOfficial: 'Other selected-host material', independent: 'Other-host coverage · independence unverified', associatedUnverified: 'Associated hosts · unverified', historical: 'Historical observations' };

function downloadFile(name, value, mime = 'application/json') {
  const body = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  const url = URL.createObjectURL(new Blob([body], { type: mime }));
  const a = document.createElement('a');
  a.href = url; a.download = name;
  try { document.body.appendChild(a); a.click(); }
  finally { a.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
}

export default function Research() {
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState('evidence');
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [contentStatus, setContentStatus] = useState('all');
  const [page, setPage] = useState(0);
  const [domain, setDomain] = useState('');
  const [dossier, setDossier] = useState(null);
  const [paste, setPaste] = useState('');
  const [exportPreview, setExportPreview] = useState(null);
  const [exportNotice, setExportNotice] = useState('');
  const [copyStatus, setCopyStatus] = useState('');
  const [jobImportReset, setJobImportReset] = useState(0);
  const [accountReset, setAccountReset] = useState(0);
  const [scanReset, setScanReset] = useState(0);
  const sequence = useRef(0);
  const exportSequence = useRef(0);
  const fileInput = useRef(null);
  useEffect(() => () => { ++sequence.current; ++exportSequence.current; }, []);
  const rows = useMemo(() => report ? filterRecords(report, { query, kind, contentStatus }) : [], [report, query, kind, contentStatus]);
  const recordMap = useMemo(() => new Map((report?.records || []).map(r => [r.id, r])), [report]);

  function resetExport() {
    ++exportSequence.current; setExportPreview(null); setExportNotice(''); setCopyStatus('');
  }
  function acceptReport(next) {
    setReport(next); setError(''); setPage(0); setQuery(''); setKind('all'); setContentStatus('all'); setDossier(null); setDomain('');
    resetExport();
  }
  function accept(text, name) { acceptReport(parseReport(text, name)); }
  function acceptFyndReport(next) {
    setAccountReset(value => value + 1);
    setScanReset(value => value + 1);
    ++sequence.current; setBusy(false); acceptReport(next);
  }
  function onFyndBusy(active) {
    if (active) { ++sequence.current; setBusy(false); setAccountReset(value => value + 1); setScanReset(value => value + 1); }
  }
  function acceptAccountReport(next) {
    ++sequence.current; setBusy(false); setJobImportReset(value => value + 1); setScanReset(value => value + 1); acceptReport(next);
  }
  function onAccountBusy(active) {
    if (active) { ++sequence.current; setBusy(false); setJobImportReset(value => value + 1); setScanReset(value => value + 1); }
  }
  function acceptScanReport(next) {
    ++sequence.current; setBusy(false); setJobImportReset(value => value + 1); setAccountReset(value => value + 1); acceptReport(next);
  }
  function onScanBusy(active) {
    if (active) { ++sequence.current; setBusy(false); setJobImportReset(value => value + 1); setAccountReset(value => value + 1); }
  }
  async function importFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setAccountReset(value => value + 1);
    setJobImportReset(value => value + 1);
    setScanReset(value => value + 1);
    const version = ++sequence.current;
    setBusy(true); setError('');
    try {
      if (file.size > 20 * 1024 * 1024) throw new Error('Choose a file smaller than 20 MB. Raw reports are limited to 5 MB.');
      const text = await file.text();
      if (version === sequence.current) accept(text, file.name);
    } catch (e) { if (version === sequence.current) setError(e.message || 'This report could not be read.'); }
    finally { if (version === sequence.current) setBusy(false); }
  }
  function importPaste() {
    setAccountReset(value => value + 1);
    setJobImportReset(value => value + 1);
    setScanReset(value => value + 1);
    ++sequence.current; setBusy(false);
    try { accept(paste, 'pasted.json'); setPaste(''); } catch (e) { setError(e.message || 'Invalid report.'); }
  }
  function clear() {
    setAccountReset(value => value + 1);
    setJobImportReset(value => value + 1);
    setScanReset(value => value + 1);
    ++sequence.current; setBusy(false); setReport(null); setDossier(null); setPaste(''); setError('');
    resetExport();
  }
  function exportData(csv = false) {
    try {
      const bundle = exportReport(report);
      const name = csv ? 'fynd-evidence.csv' : 'fynd-research-bundle.json';
      const text = csv ? bundle.files['evidence.csv'] : JSON.stringify(bundle, null, 2);
      ++exportSequence.current; setExportPreview({ name, text }); setCopyStatus(''); setError('');
      setExportNotice('Download requested. This page cannot confirm whether your browser saved the file.');
      try { downloadFile(name, text, csv ? 'text/csv;charset=utf-8' : 'application/json'); }
      catch { setExportNotice('The download could not be started. Your export text is still available below.'); }
    } catch (e) { setError(e.message || 'Download could not be created.'); }
  }
  async function copyExport() {
    if (!exportPreview) return;
    const version = exportSequence.current;
    setCopyStatus('Copying…');
    try {
      if (typeof navigator.clipboard?.writeText !== 'function') throw new Error('Clipboard unavailable.');
      await navigator.clipboard.writeText(exportPreview.text);
      if (version === exportSequence.current) setCopyStatus('Export copied. Paste it into a text file and save it with the filename shown above.');
    } catch {
      if (version === exportSequence.current) setCopyStatus('Clipboard access is unavailable. Select all text in the Export text box, copy it manually, and save it with the filename shown above.');
    }
  }
  function applyDomain(event) {
    event.preventDefault();
    try { setDossier(buildDossier(report, domain)); setError(''); } catch (e) { setDossier(null); setError(e.message || 'Enter a valid company hostname.'); }
  }
  function resetFilter(setter, value) { setter(value); setPage(0); }

  return <div className="max-w-6xl mx-auto space-y-6" data-testid="research-page">
    <header className="flex flex-col sm:flex-row justify-between gap-5">
      <div>
        <div className="text-xs font-medium uppercase tracking-widest text-accent mb-2">LYNK Collider · Research workspace</div>
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">See the evidence. Keep the context.</h1>
        <p className="muted text-sm mt-3 max-w-2xl">Filter sources, inspect research relationships, organize a company dossier, and take the discovery trail with you.</p>
      </div>
      <div className="flex items-start gap-2 shrink-0">
        <input ref={fileInput} type="file" accept=".json,.jsonl,application/json" className="sr-only" aria-label="Import evidence report" onChange={importFile} />
        <button className="liquid-capsule liquid-primary" type="button" disabled={busy} onClick={() => fileInput.current?.click()}><Upload size={16} />{busy ? 'Reading…' : 'Import report'}</button>
      </div>
    </header>

    <div className="liquid-card p-4 text-sm flex flex-col sm:flex-row gap-3 justify-between" role="note" aria-label="Research evidence scope">
      <div><strong>Source evidence, not verified claims.</strong> Scan availability depends on the configured service and permitted sources. Source claims are not independently verified.</div>
      <div className="muted sm:max-w-xs">Manual imports are processed in this tab unless you explicitly save to your account. Starting a scan explicitly stores source content through the scan service. Clearing this tab does not delete saved account copies or scan records.</div>
    </div>
    <ResearchScanPanel onImportReport={acceptScanReport} onBusy={onScanBusy} resetKey={scanReset} />
    <ResearchAccountLibrary report={report} onReport={acceptAccountReport} onBusy={onAccountBusy} resetKey={accountReset} />
    {error && <div role="alert" className="rounded-xl border border-red-400 p-4 text-sm">{error} {report && 'Your previously loaded report is unchanged.'}</div>}

    {!report ? <section className="liquid-sheet p-6 sm:p-10 space-y-6" data-testid="research-empty">
      <FyndJobResearchImport onReport={acceptFyndReport} onBusy={onFyndBusy} resetKey={jobImportReset} />
      <div className="max-w-2xl"><BookOpen className="text-accent mb-4" size={28} /><h2 className="text-2xl font-semibold">A clearer view of what you actually found.</h2><p className="muted mt-3">Import a Collider run, an evidence JSON/JSONL file, or a downloaded research bundle. Up to 1,000 evidence records. Raw reports: 5 MB; portable bundles: 20 MB. Missing content and missing discovery history stay visible.</p></div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">{tabs.map(([key, title, Icon]) => <div key={key} className="border border-line dark:border-line-dark rounded-2xl p-4"><Icon size={18} className="mb-3 text-accent" /><h3 className="font-medium text-sm">{title}</h3><p className="muted text-xs mt-2">{({ evidence: 'Separate evidence kind from how much content was obtained.', links: 'Inspect shared identifiers without merging distinct records.', company: 'Separate selected-host material, external coverage, and history.', trace: 'Export retained records and disclose what was never captured.' })[key]}</p></div>)}</div>
      <details className="border-t border-line dark:border-line-dark pt-4"><summary className="cursor-pointer text-sm font-medium">Paste report JSON or get an example format</summary><div className="mt-4 space-y-3">
        <label className="block text-sm" htmlFor="report-paste">Report JSON</label><textarea id="report-paste" className={`${inputClass} font-mono min-h-40`} value={paste} maxLength={20 * 1024 * 1024} onChange={e => setPaste(e.target.value)} placeholder={'{"title":"My research","records":[…]}'} />
        <div className="flex flex-wrap gap-2"><button type="button" className="liquid-capsule liquid-primary" disabled={!paste.trim()} onClick={importPaste}>Open pasted report</button><button type="button" className="liquid-capsule liquid-secondary" onClick={() => downloadFile('fynd-report-template.json', { title: 'Example format — replace with your own evidence', records: [{ id: 'source-1', url: 'https://example.org/evidence', title: 'Example record — not real research', kind: 'unknown', contentStatus: 'metadata-only', content: '', identifiers: { doi: [], pmid: [], trial: [] } }] })}>Download template</button></div>
      </div></details>
    </section> : <>
      <section className="liquid-card p-5 space-y-4">
        <div className="flex flex-wrap gap-3 justify-between items-center"><div className="min-w-0"><h2 className="text-xl font-semibold break-words">{report.title || 'Imported research'}</h2><p className="text-xs muted mt-1">{report.records.length} retained evidence records · {report.relations.length} identifier {report.relations.length === 1 ? 'relationship' : 'relationships'}</p></div><div className="flex flex-wrap gap-2"><button type="button" className="liquid-capsule liquid-secondary" onClick={() => exportData(false)}><Download size={15} />Download bundle</button><button type="button" className="liquid-capsule liquid-secondary" onClick={clear}><X size={15} />Clear report</button></div></div>
        {!!report.warnings?.length && <details><summary className="cursor-pointer text-xs muted">Import notes ({report.warnings.length})</summary><ul className="list-disc pl-5 text-xs muted mt-2 space-y-1">{report.warnings.map((warning, i) => <li key={i}>{typeof warning === 'string' ? warning : JSON.stringify(warning)}</li>)}</ul></details>}
      </section>
      {report.runSummary && <section className="liquid-card p-5 space-y-3" aria-labelledby="run-summary-heading">
        <h2 id="run-summary-heading" className="text-lg font-semibold">Imported Collider run</h2>
        <p className="text-sm">Run status: {label(report.runSummary.status)} · {report.runSummary.progress.done} of {report.runSummary.progress.total} recorded steps settled</p>
        <p className="text-xs muted break-all">Run ID: {report.runSummary.id}</p>
        <p className="text-xs muted">Saved pages: {report.runSummary.counts.savedPages} · Saved jobs: {report.runSummary.counts.savedJobs} · Structured records: {report.runSummary.counts.structuredRecords} · Successful empty boards: {report.runSummary.counts.successfulEmptyBoards}</p>
        <p className="text-xs muted">Imported run state only; completeness and internet coverage are not independently verified. {report.runSummary.incomplete ? 'The source marks this run incomplete.' : 'A completed run does not establish complete search coverage.'}</p>
        <details><summary className="cursor-pointer text-sm font-medium">Run diagnostics and summary</summary><pre className="mt-3 text-xs whitespace-pre-wrap break-words max-h-80 overflow-y-auto">{JSON.stringify(report.runSummary, null, 2)}</pre></details>
      </section>}
      {exportPreview && <section className="liquid-card p-5 space-y-3" aria-labelledby="export-heading">
        <div className="flex flex-wrap justify-between items-start gap-3"><div className="min-w-0"><h2 id="export-heading" className="text-lg font-semibold">Your export is ready</h2><p className="text-xs muted mt-1 break-all">Filename: {exportPreview.name}</p></div><button type="button" className="liquid-capsule liquid-secondary" onClick={copyExport} disabled={copyStatus === 'Copying…'}>Copy export</button></div>
        <p className="text-sm muted" role="status">{exportNotice}</p>
        <p className="text-xs muted">If no file appears, copy the text below and save it with the filename shown above. The preview is kept in this tab and removed when you clear or replace the report. Downloaded files and clipboard copies are not removed.</p>
        <label className="block text-xs muted" htmlFor="export-text">Export text</label><textarea id="export-text" className={`${inputClass} font-mono h-48 resize-y`} value={exportPreview.text} readOnly spellCheck={false} wrap="off" />
        {copyStatus && <p className="text-sm muted" role="status">{copyStatus}</p>}
      </section>}
      <nav className="flex gap-2 flex-wrap" aria-label="Research views">{tabs.map(([key, title, Icon]) => <button key={key} type="button" aria-pressed={tab === key} onClick={() => setTab(key)} className={`liquid-capsule ${tab === key ? 'liquid-primary' : 'liquid-secondary'}`}><Icon size={15} />{title}</button>)}</nav>

      {tab === 'evidence' && <section className="space-y-4">
        <div className="grid md:grid-cols-3 gap-3"><label className="text-xs muted space-y-1"><span className="flex items-center gap-1"><Search size={12} />Search this report</span><input value={query} onChange={e => resetFilter(setQuery, e.target.value)} className={inputClass} placeholder="Title, source, identifier…" /></label><label className="text-xs muted space-y-1">Evidence kind<select className={inputClass} value={kind} onChange={e => resetFilter(setKind, e.target.value)}><option value="all">All kinds</option>{REPORT_KINDS.map(v => <option key={v} value={v}>{label(v)}</option>)}</select></label><label className="text-xs muted space-y-1">Content obtained<select className={inputClass} value={contentStatus} onChange={e => resetFilter(setContentStatus, e.target.value)}><option value="all">All content states</option>{CONTENT_STATUSES.map(v => <option key={v} value={v}>{label(v)}</option>)}</select></label></div>
        <div className="flex justify-between text-xs muted items-center"><span role="status">{rows.length} matching records</span><button type="button" className="liquid-capsule liquid-secondary" onClick={() => exportData(true)}>Export all evidence CSV</button></div>
        {rows.length ? rows.slice(page * 25, (page + 1) * 25).map(r => <article key={r.id} className="liquid-card p-5 space-y-3" data-testid="evidence-record">
          <div className="flex flex-wrap justify-between gap-3"><div className="min-w-0"><div className="text-xs muted break-all">{r.hostname || 'No valid source URL'} · {r.source || 'Source unspecified'}</div><h3 className="font-semibold mt-1 break-words">{r.title || 'Untitled evidence'}</h3></div><div className="flex flex-wrap gap-2 text-xs items-start"><span className="liquid-pill">{label(r.kind)}</span><span className="liquid-pill">{label(r.contentStatus)}</span></div></div>
          <p className="text-xs muted">{r.contentBasis}</p>
          {r.content && <details><summary className="text-sm cursor-pointer">Read retained content</summary><pre className="mt-3 text-sm whitespace-pre-wrap break-words font-sans max-h-80 overflow-y-auto">{r.content}</pre></details>}
          <div className="flex flex-wrap gap-3 text-xs"><span className="muted break-all">Record {r.id}</span>{r.url && <a href={r.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" className="inline-flex items-center gap-1">Open source<ExternalLink size={12} /></a>}</div>
        </article>) : <p className="liquid-card p-6 muted">{report.records.length ? 'No records match these filters. Try a different evidence kind or content state.' : 'This imported run contains no collected evidence. Review the run summary and Discovery trail for retained diagnostics. Empty results do not prove absence.'}</p>}
        {rows.length > 25 && <div className="flex items-center justify-center gap-4"><button className="liquid-capsule liquid-secondary" disabled={page === 0} onClick={() => setPage(p => p - 1)}>Previous</button><span className="text-xs muted">Page {page + 1} of {Math.ceil(rows.length / 25)}</span><button className="liquid-capsule liquid-secondary" disabled={(page + 1) * 25 >= rows.length} onClick={() => setPage(p => p + 1)}>Next</button></div>}
      </section>}

      {tab === 'links' && <section className="liquid-card p-5 space-y-4"><h2 className="text-xl font-semibold">Related, not interchangeable.</h2><p className="text-sm muted">Links use identifiers observed in your import. A registration, publication, PDF, and news story stay separate records. A shared identifier is not independent corroboration or proof of equivalent findings.</p>{report.relations.length ? <ul className="space-y-3">{report.relations.slice(0, 200).map((relation, i) => <li key={relation.id || i} className="rounded-xl border border-line dark:border-line-dark p-3 text-sm break-words"><div>{recordMap.get(relation.sourceId)?.title || relation.sourceId} <span className="muted">↔</span> {recordMap.get(relation.targetId)?.title || relation.targetId}</div><p className="text-xs muted mt-1">{label(relation.type || 'shared identifier')} · {relation.identifier || ''}</p></li>)}</ul> : <p className="muted text-sm">No safe identifier links were found. Nothing was merged or inferred from similar titles.</p>}{report.relations.length > 200 && <p className="text-xs muted">Showing the first 200 relationships; the bundle retains all exported relationships.</p>}</section>}

      {tab === 'company' && <section className="space-y-4"><div className="liquid-card p-5 space-y-3"><h2 className="text-xl font-semibold">Company dossier</h2><p className="text-sm muted">Choose a company hostname already represented in the report. This organizes retained evidence; it does not fetch new pages or verify domain ownership. Other hosts, including subdomains, are not silently treated as official.</p><form onSubmit={applyDomain} className="flex flex-col sm:flex-row gap-2"><label className="flex-1"><span className="sr-only">Company hostname</span><input className={inputClass} placeholder="example.com" value={domain} onChange={e => setDomain(e.target.value)} required /></label><button className="liquid-capsule liquid-primary">Organize dossier</button></form></div>{dossier && <><p className="text-xs muted">Selected host: {dossier.domain} · First-party statements are not independent verification.</p>{dossier.warnings?.map((w, i) => <p key={i} className="text-xs muted">{w}</p>)}<div className="grid md:grid-cols-2 gap-4">{Object.entries(dossier.sections).map(([key, entries]) => <section key={key} className="liquid-card p-5 space-y-3"><h3 className="font-semibold">{sectionNames[key] || label(key)}</h3>{entries.length ? <ul className="text-sm space-y-2">{entries.slice(0, 30).map(r => <li key={r.id}>{r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">{r.title || r.url}</a> : r.title}<span className="block text-xs muted">{r.hostname} · {label(r.contentStatus)}</span></li>)}</ul> : <p className="muted text-sm">No retained evidence in this section.</p>}{entries.length > 30 && <p className="text-xs muted">{entries.length - 30} more records remain in the evidence view and download.</p>}</section>)}</div></>}</section>}

      {tab === 'trace' && <section className="liquid-card p-5 space-y-5"><h2 className="text-xl font-semibold">A portable, inspectable trail.</h2><p className="text-sm muted">The download is one JSON bundle containing a manifest and named CSV/JSONL files. It describes only what the import retained—not every upstream search result or a complete archive.</p><div className="grid sm:grid-cols-3 gap-3">{[['Candidates', report.trace.candidates.length], ['Fetch outcomes', report.trace.outcomes.length], ['Discovery edges', report.trace.edges.length]].map(([title, count]) => <div className="border border-line dark:border-line-dark rounded-xl p-4" key={title}><div className="text-2xl font-semibold">{count}</div><div className="text-xs muted">Retained {title.toLowerCase()}</div></div>)}</div><div><h3 className="text-sm font-medium mb-2">Missing or omitted information</h3><ul className="list-disc pl-5 text-sm muted space-y-2">{(report.omissions.length ? report.omissions : ['No additional omissions declared by this import; completeness is not independently verified.']).map((v, i) => <li key={i}>{typeof v === 'string' ? v : JSON.stringify(v)}</li>)}</ul></div><button type="button" onClick={() => exportData(false)} className="liquid-capsule liquid-primary"><Download size={16} />Download traceable bundle</button></section>}
    </>}
  </div>;
}
