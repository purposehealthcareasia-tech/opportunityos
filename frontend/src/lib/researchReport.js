// Local-only evidence tools. Imported assertions are not independently verified.
export const REPORT_KINDS = ['studies', 'trials', 'datasets', 'news', 'code', 'video', 'documents', 'jobs', 'web', 'unknown'];
export const CONTENT_STATUSES = ['full', 'partial', 'metadata-only', 'unknown'];
const MAX_BYTES = 5 * 1024 * 1024, MAX_NORMALIZED_BYTES = 10 * 1024 * 1024, MAX_BUNDLE_BYTES = 20 * 1024 * 1024, MAX_RECORDS = 1000, MAX_TRACE = 5000;
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
function truncateText(value, maximum) {
  let end = Math.min(value.length, maximum);
  // Never manufacture a lone surrogate by cutting a valid supplementary
  // character in half. Pre-existing invalid surrogates are not repaired here.
  if (end > 0 && end < value.length && value.charCodeAt(end - 1) >= 0xd800 && value.charCodeAt(end - 1) <= 0xdbff && value.charCodeAt(end) >= 0xdc00 && value.charCodeAt(end) <= 0xdfff) end--;
  return value.slice(0, end);
}
// eslint-disable-next-line no-control-regex -- Intentionally remove non-printing ASCII controls from imported text.
const clean = (value, max = 500) => typeof value === 'string' ? truncateText(value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').trim(), max) : '';
const list = value => value == null ? [] : Array.isArray(value) ? value : [value];
const fail = message => { throw new Error(message); };
const byteLength = value => new Blob([value]).size;
function hash(value) {
  let a = 2166136261, b = 5381;
  for (let i = 0; i < value.length; i++) { a = Math.imul(a ^ value.charCodeAt(i), 16777619); b = Math.imul(b, 33) ^ value.charCodeAt(i); }
  return (a >>> 0).toString(16).padStart(8, '0') + (b >>> 0).toString(16).padStart(8, '0');
}
function inspect(input, maxBytes = MAX_BYTES) {
  let nodes = 0;
  const visit = (value, depth) => {
    if (++nodes > 150000 || depth > 20) fail('This report is too complex. Use a smaller export.');
    if (Array.isArray(value)) { if (value.length > MAX_TRACE) fail('An input list exceeds 5,000 items.'); value.forEach(child => visit(child, depth + 1)); }
    else if (object(value)) {
      if (![Object.prototype, null].includes(Object.getPrototypeOf(value))) fail('Only plain JSON data is supported.');
      Object.keys(value).forEach(key => { if (['__proto__', 'constructor', 'prototype'].includes(key)) fail('Unsafe object key in report.'); visit(value[key], depth + 1); });
    } else if (value !== null && (!['string', 'number', 'boolean'].includes(typeof value) || (typeof value === 'number' && !Number.isFinite(value)))) fail('Only finite JSON data is supported.');
  };
  visit(input, 0);
  if (byteLength(JSON.stringify(input)) > maxBytes) fail('Report exceeds the import size limit (5 MB raw or 10 MB reconstructed).');
}
function publicUrl(value) {
  // eslint-disable-next-line no-control-regex -- Intentionally reject whitespace, ASCII controls and backslashes in source URLs.
  if (typeof value !== 'string' || value.length > 2048 || /[\u0000-\u0020\\]/.test(value)) fail('A record contains an invalid or unsafe URL.');
  let url;
  try { url = new URL(value); } catch { fail('Every evidence record needs an absolute public http(s) URL.'); }
  const host = url.hostname.toLowerCase();
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.port || !host.includes('.') ||
      /(^|\.)(localhost|local|internal|intranet|test|invalid|onion)$/.test(host) || /^[\d.]+$/.test(host) || host.includes(':') || host.endsWith('.')) fail('Only public http(s) hostnames without credentials or custom ports are supported.');
  url.hash = '';
  return url.href;
}
const urlId = url => `url_${hash(url)}`;
const date = value => typeof value === 'string' && /^\d{4}-\d\d-\d\d/.test(value) && Number.isFinite(Date.parse(value)) ? value.slice(0, 40) : '';
function kindOf(row) {
  const names = [row.kind, row.evidenceKind, ...list(row.types), row.data?.['@type']].flat().map(value => clean(value).toLowerCase());
  const map = { paper: 'studies', study: 'studies', scholarlyarticle: 'studies', trial: 'trials', clinicaltrial: 'trials', dataset: 'datasets', newsarticle: 'news', software: 'code', sourcecode: 'code', videoobject: 'video', doc: 'documents', document: 'documents', pdf: 'documents', job: 'jobs', jobposting: 'jobs', article: 'web', webpage: 'web', blogposting: 'web' };
  return names.map(name => REPORT_KINDS.includes(name) ? name : map[name]).find(Boolean) || 'unknown';
}
function observedIdentifiers(row, url) {
  const result = { doi: [], pmid: [], trial: [] };
  const add = (type, value) => {
    if (typeof value !== 'string' && typeof value !== 'number') return;
    let text = String(value).trim();
    if (type === 'doi') text = text.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '').toLowerCase();
    if (type === 'pmid') text = text.replace(/^pmid:\s*/i, '');
    if (type === 'trial') text = text.toUpperCase();
    const valid = type === 'doi' ? /^10\.\d{4,9}\/[-._;()/:a-z0-9]+$/.test(text) : type === 'pmid' ? /^[1-9]\d{0,9}$/.test(text) : /^(NCT\d{8}|ISRCTN\d{8})$/.test(text);
    if (valid && text.length <= 200 && !result[type].includes(text) && result[type].length < 20) result[type].push(text);
  };
  for (const values of [row, row.identifiers, row.data]) if (object(values)) {
    for (const type of ['doi', 'pmid', 'trial']) list(values[type]).forEach(value => add(type, value));
    list(values.trialId).forEach(value => add('trial', value));
  }
  const parsed = new URL(url), host = parsed.hostname, path = parsed.pathname;
  if (['doi.org', 'dx.doi.org'].includes(host)) { try { add('doi', decodeURIComponent(path.slice(1))); } catch { /* malformed encoded identifier is ignored */ } }
  if (host === 'pubmed.ncbi.nlm.nih.gov') add('pmid', path.split('/')[1]);
  if (['clinicaltrials.gov', 'www.clinicaltrials.gov'].includes(host)) add('trial', path.match(/(?:^|\/)(NCT\d{8})(?:\/|$)/i)?.[1]);
  Object.values(result).forEach(values => values.sort());
  return result;
}
function normalizeRecord(row, position, used, warnings) {
  if (!object(row)) fail(`Evidence item ${position + 1} must be an object.`);
  const url = publicUrl(row.url || row.sourceUrl), body = [row.content, row.markdown, row.text].find(value => typeof value === 'string' && value.trim()) || '';
  const snippet = [row.snippet, row.abstract, row.data?.description].find(value => typeof value === 'string' && value.trim()) || '';
  const content = clean(body || snippet, 60000), declared = String(row.contentStatus || row.content_status || '').replace('metadata_only', 'metadata-only');
  const truncated = row.truncated === true || row.structuredTruncated === true || body.length > 60000 || snippet.length > 60000;
  let contentStatus = !content ? 'metadata-only' : truncated || !body ? 'partial' : CONTENT_STATUSES.includes(declared) ? declared : 'unknown';
  if (declared === 'full' && !body) warnings.push('A full-content claim without a retained body was downgraded.');
  if (declared === 'metadata-only') contentStatus = 'metadata-only';
  const association = object(row.association) ? { domain: clean(row.association.domain, 253), claim: clean(row.association.claim || row.association.type), evidenceUrl: row.association.evidenceUrl ? publicUrl(row.association.evidenceUrl) : '' } : null;
  const record = {
    sourceId: clean(row.sourceId ?? row.id, 200), url, urlId: urlId(url), hostname: new URL(url).hostname,
    title: clean(row.title || row.data?.headline || row.data?.name) || new URL(url).hostname,
    kind: kindOf(row), contentStatus, content,
    contentBasis: contentStatus === 'full' ? 'Imported full-content assertion; not independently verified.' : contentStatus === 'partial' ? 'Retained excerpt or explicit truncation.' : contentStatus === 'metadata-only' ? 'Metadata-only; no full-content claim.' : 'Body retained; completeness unknown.',
    identifiers: observedIdentifiers(row, url), publishedAt: date(row.publishedAt || row.published_at || row.date || row.data?.datePublished),
    source: clean(row.source || row.provider, 200), section: clean(row.section, 40).toLowerCase(),
    historical: row.historical === true || row.archived === true, association,
  };
  const baseId = `evidence_${hash(JSON.stringify(record))}`;
  let id = baseId, duplicate = 1;
  while (used.has(id)) id = `${baseId}_${++duplicate}`;
  used.add(id);
  return { id, ...record };
}
function linkRecords(records, warnings) {
  const groups = new Map(), relations = [];
  records.forEach(record => Object.entries(record.identifiers).forEach(([type, values]) => values.forEach(value => {
    const key = `${type}:${value}`; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(record);
  })));
  for (const [identifier, group] of groups) {
    // A bounded star is enough to link a group; it avoids quadratic expansion.
    const first = group[0];
    for (const other of group.slice(1)) {
      const conflict = ['doi', 'pmid'].some(type => first.identifiers[type].length && other.identifiers[type].length && !first.identifiers[type].some(value => other.identifiers[type].includes(value)));
      if (conflict && !identifier.startsWith('trial:')) { warnings.push('Conflicting publication identifiers prevented a proposed relation.'); continue; }
      relations.push({ id: `relation_${hash(`${first.id}|${other.id}|${identifier}`)}`, sourceId: first.id, targetId: other.id,
        type: identifier.startsWith('trial:') ? 'shared-trial-reference' : 'shared-publication-identifier', identifier,
        basis: 'Observed in imported structured fields or source URL; records remain distinct.', independentEvidence: 'not-established' });
    }
  }
  return relations;
}
function arrayField(value, label) {
  if (value == null) return [];
  if (!Array.isArray(value)) fail(`${label} must be an array.`);
  if (value.length > MAX_TRACE) fail(`${label} exceeds 5,000 items.`);
  return value;
}
const RUN_STATES = ['queued', 'running', 'paused', 'cancel_requested', 'completed', 'partial', 'failed', 'cancelled'];
const RUN_COUNTS = ['savedPages', 'savedJobs', 'structuredRecords', 'successfulEmptyBoards', 'selectedPages', 'attemptedPages', 'discoveredUrls', 'notFetched', 'frontierOmitted', 'linksSkipped', 'omittedRecords', 'truncatedRecords'];
const RUN_PROGRESS = ['total', 'done', 'pending', 'inflight', 'completed', 'partial', 'failed', 'uncertain'];
const nonnegative = value => Number.isSafeInteger(value) && value >= 0;
function normalizeRunSummary(value) {
  if (!object(value) || value.format !== 'lynk-collider-run-v1' || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value.id || '') ||
      !RUN_STATES.includes(value.status) || !object(value.input) || !object(value.counts) || !object(value.progress) ||
      !RUN_COUNTS.every(key => nonnegative(value.counts[key])) || !RUN_PROGRESS.every(key => nonnegative(value.progress[key])) ||
      typeof value.incomplete !== 'boolean') fail('Invalid Collider run summary. Include its run ID, input, status, progress and counts.');
  const bounded = (rows, name, limit) => {
    const values = arrayField(rows, name);
    if (values.length > limit) fail(`${name} exceeds the supported run-summary limit (${limit}).`);
    return values;
  };
  const supplied = value.input;
  if (!Array.isArray(supplied.urls) || !Array.isArray(supplied.boards) || !Number.isSafeInteger(supplied.pageLimit) || supplied.pageLimit < 1 || typeof supplied.followLinks !== 'boolean') fail('Invalid Collider run input.');
  const input = { urls: bounded(supplied.urls, 'run input URLs', 20).map(publicUrl), boards: bounded(supplied.boards, 'run input boards', 3).map(board => {
    if (!object(board) || !clean(board.provider, 50) || !clean(board.board, 80)) fail('Invalid Collider board input.');
    return { provider: clean(board.provider, 50), board: clean(board.board, 80), ...(nonnegative(board.limit) ? { limit: board.limit } : {}) };
  }), pageLimit: supplied.pageLimit, followLinks: supplied.followLinks };
  if (supplied.query !== undefined) { if (!clean(supplied.query, 400)) fail('Invalid Collider query.'); input.query = clean(supplied.query, 400); }
  if (!input.urls.length && !input.boards.length && !input.query) fail('A Collider run needs an explicit query, source URL or board.');
  for (const [key, limit, length] of [['providers', 4, 50], ['querySlices', 3, 400]]) if (supplied[key] !== undefined) {
    input[key] = bounded(supplied[key], `run ${key}`, limit).map(item => { if (!clean(item, length)) fail(`Invalid run ${key}.`); return clean(item, length); });
  }
  if (supplied.maxDepth !== undefined) { if (!nonnegative(supplied.maxDepth) || supplied.maxDepth > 2) fail('Invalid Collider depth.'); input.maxDepth = supplied.maxDepth; }
  if (supplied.crawlMode !== undefined) { if (!['jobs', 'web'].includes(supplied.crawlMode)) fail('Invalid Collider crawl mode.'); input.crawlMode = supplied.crawlMode; }
  const counts = Object.fromEntries(RUN_COUNTS.map(key => [key, value.counts[key]]));
  const progress = Object.fromEntries(RUN_PROGRESS.map(key => [key, value.progress[key]]));
  if (RUN_PROGRESS.slice(2).reduce((sum, key) => sum + progress[key], 0) !== progress.total ||
      ['completed', 'partial', 'failed', 'uncertain'].reduce((sum, key) => sum + progress[key], 0) !== progress.done) fail('Collider progress counters are inconsistent.');
  const diagnostics = (rows, name) => bounded(rows, name, 1000).map(row => {
    if (!object(row) || !clean(row.code, 100)) fail(`Invalid ${name} entry.`);
    return { code: clean(row.code, 100), unitId: clean(row.unitId, 200), source: clean(row.source, 200), url: row.url ? publicUrl(row.url) : '' };
  });
  const searchSlices = bounded(value.searchSlices, 'run search slices', 4).map(slice => {
    if (!object(slice)) fail('Invalid run search slice.');
    return { unitId: clean(slice.unitId, 200), query: clean(slice.query, 400), status: clean(slice.status, 80), returned: nonnegative(slice.returned) ? slice.returned : null,
      providers: bounded(slice.providers, 'run search providers', 4).map(provider => {
        if (!object(provider)) fail('Invalid run search provider.');
        return { id: clean(provider.id, 50), status: clean(provider.status, 80), code: clean(provider.code, 100), returned: nonnegative(provider.returned) ? provider.returned : null };
      }), completeness: 'unknown' };
  });
  return { format: 'lynk-collider-run-v1', id: value.id.toLowerCase(), status: value.status, input, progress, counts, incomplete: value.incomplete,
    createdAt: date(value.createdAt), updatedAt: date(value.updatedAt), finishedAt: date(value.finishedAt),
    coverageScope: clean(value.coverageScope, 1000), selectionPriority: clean(value.selectionPriority, 1000),
    errors: diagnostics(value.errors, 'run errors'), warnings: diagnostics(value.warnings, 'run warnings'), searchSlices };
}
function colliderRunSummary(root, payload) {
  // Recognize a detailed Collider run, not an arbitrary object containing empty arrays.
  if (!object(root.result) || !['pages', 'jobs', 'records'].every(key => Array.isArray(payload[key])) ||
      typeof root.id !== 'string' || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(root.id) ||
      !RUN_STATES.includes(root.status) || !object(root.input) || !object(root.progress) || !object(payload.counts)) return null;
  return normalizeRunSummary({ format: 'lynk-collider-run-v1', id: root.id, status: root.status, input: root.input, progress: root.progress, counts: payload.counts,
    incomplete: payload.incomplete, createdAt: root.createdAt, updatedAt: root.updatedAt, finishedAt: root.finishedAt,
    coverageScope: payload.coverage?.scope, selectionPriority: payload.selectionPriority, errors: payload.errors, warnings: payload.warnings,
    searchSlices: payload.searchSlices ?? (object(payload.discovery) ? [payload.discovery] : []) });
}
function normalizeTrace(root, payload, records, omissions) {
  const trace = object(root.trace) ? root.trace : {}, candidates = [], outcomes = [], edges = [];
  const discoveries = [payload.discovery, ...arrayField(payload.searchSlices, 'searchSlices')].filter(object);
  const inputs = [...arrayField(trace.candidates ?? root.candidates ?? payload.candidates, 'candidates'), ...discoveries.flatMap(value => arrayField(value.results, 'discovery results'))];
  const seen = new Set();
  for (const item of inputs) {
    const row = typeof item === 'string' ? { url: item } : item;
    if (!object(row)) fail('Invalid discovery candidate.');
    const url = publicUrl(row.url), source = clean(row.source || row.provider, 200), reason = clean(row.reason, 1000);
    const sources = list(row.sources).slice(0, 20).map(value => object(value) ? { provider: clean(value.provider, 200), kind: clean(value.kind, 80), rank: Number.isSafeInteger(value.rank) && value.rank >= 0 ? value.rank : null } : { provider: clean(value, 200), kind: '', rank: null }).filter(value => value.provider);
    const result = { url, urlId: urlId(url), selected: typeof row.selected === 'boolean' ? row.selected : null, reason: reason || null, source, title: clean(row.title), snippet: clean(row.snippet, 2000), sources, score: typeof row.score === 'number' && Number.isFinite(row.score) ? row.score : null, scoreBasis: 'Imported ranking value; not a truth or confidence score.' };
    const key = JSON.stringify(result); if (seen.has(key)) continue; seen.add(key);
    candidates.push({ id: `candidate_${hash(key)}`, ...result });
  }
  const recordedOutcomes = arrayField(trace.outcomes ?? root.outcomes ?? payload.outcomes, 'outcomes');
  const units = arrayField(root.units, 'units').filter(unit => object(unit) && unit.kind === 'page' && unit.input?.url);
  for (const row of [...recordedOutcomes, ...units.map(unit => ({ url: unit.input.url, status: unit.status, reason: unit.error || '', sourceId: unit.id }))]) {
    if (!object(row)) fail('Invalid fetch outcome.');
    const url = publicUrl(row.url), status = clean(row.status, 80) || 'unknown', reason = clean(row.reason || row.code, 1000) || null;
    const result = { url, urlId: urlId(url), status, reason, sourceId: clean(row.sourceId ?? row.id, 200), evidenceIds: records.filter(record => record.url === url).map(record => record.id), evidenceLinkBasis: 'Same URL only; the producing fetch attempt is unknown.' };
    outcomes.push({ id: `outcome_${hash(JSON.stringify(result))}_${outcomes.length + 1}`, ...result });
  }
  for (const row of arrayField(trace.edges ?? root.edges ?? payload.edges, 'edges')) {
    if (!object(row)) fail('Invalid source-to-target edge.');
    const sourceUrl = publicUrl(row.sourceUrl || row.from), targetUrl = publicUrl(row.targetUrl || row.to);
    const result = { sourceUrl, sourceUrlId: urlId(sourceUrl), targetUrl, targetUrlId: urlId(targetUrl), type: clean(row.type, 80) || 'imported-link', reason: clean(row.reason, 1000) || null };
    edges.push({ id: `edge_${hash(JSON.stringify(result))}_${edges.length + 1}`, ...result });
  }
  if (candidates.length + outcomes.length + edges.length > MAX_TRACE) fail('Combined retained trace exceeds 5,000 items.');
  if (!candidates.length) omissions.push('No retained discovery candidates were supplied.');
  if (candidates.some(candidate => candidate.selected === null || !candidate.reason)) omissions.push('Some candidate selection decisions or reasons were not supplied.');
  if (!outcomes.length) omissions.push('No explicit fetch outcomes were supplied; evidence existence is not a fetch log.');
  if (!edges.length) omissions.push('No source-to-target edges were supplied; crawl lineage was not reconstructed.');
  return { candidates, outcomes, edges };
}
function normalizeReport(input, maxBytes = MAX_BYTES, portable = false) {
  inspect(input, maxBytes);
  const root = Array.isArray(input) ? { records: input } : input;
  if (!object(root)) fail('Import a report object or evidence array.');
  const payload = object(root.result) ? root.result : root;
  const rows = [...arrayField(payload.records, 'records'), ...arrayField(payload.pages, 'pages'), ...arrayField(payload.jobs, 'jobs')];
  const runSummary = portable && root.runSummary ? normalizeRunSummary(root.runSummary) : colliderRunSummary(root, payload);
  if (!rows.length && !runSummary) fail('No evidence records were found. Supply records, pages, result.pages, or a detailed Collider run with its summary.');
  if (!rows.length && ['savedPages', 'savedJobs', 'structuredRecords'].some(key => runSummary.counts[key] !== 0)) fail('The Collider summary reports saved evidence, but this export contains none. Import the detailed evidence export.');
  if (rows.length > MAX_RECORDS) fail('Report exceeds the 1,000 evidence-record limit.');
  const warnings = [], omissions = ['This package contains only retained imported data, not all upstream discoveries.', 'Source bodies, selection reasons, history and lineage absent from the input remain unavailable.', 'Dedicated raw-HTML and contact-specific fields are omitted; retained text is not automatically redacted.', 'Other unsupported fields and identifiers are omitted.'];
  for (const [name, target] of [['warnings', warnings], ['omissions', omissions]]) {
    const notes = arrayField(root[name], name);
    if (notes.length > 1000) fail(`Imported ${name} exceed the 1,000-note limit.`);
    if (notes.some(value => typeof value !== 'string' || value.length > 1000)) fail(`Imported ${name} must be strings of at most 1,000 characters each.`);
    notes.forEach(value => target.push(clean(value, 1000)));
  }
  if (root.truncated === true || payload.truncated === true) omissions.push('The source export explicitly reports truncation.');
  const records = rows.map((row, index) => normalizeRecord(row, index, new Set(), warnings));
  // Assign duplicates without collapsing their separate source records.
  const used = new Map();
  records.forEach(record => { const count = (used.get(record.id) || 0) + 1; used.set(record.id, count); if (count > 1) record.id += `_${count}`; });
  const relations = linkRecords(records, warnings), trace = normalizeTrace(root, payload, records, omissions);
  if (root.result?.counts?.frontierOmitted || root.result?.counts?.linksSkipped || root.result?.counts?.omittedRecords) omissions.push('The imported Collider summary reports omitted frontier links or records; their details were not restored.');
  const report = { schemaVersion: 1, id: `report_${hash(JSON.stringify({ records, trace, ...(runSummary ? { runSummary } : {}) }))}`, title: clean(root.title || root.query || root.input?.query) || (runSummary ? `Collider run ${runSummary.id}` : 'Imported research'),
    ...(runSummary ? { runSummary } : {}),
    records, relations, trace, omissions: [...new Set(omissions)], warnings: [...new Set(warnings)],
    stats: { records: records.length, domains: new Set(records.map(record => record.hostname)).size, relations: relations.length, candidates: trace.candidates.length, outcomes: trace.outcomes.length, edges: trace.edges.length } };
  if (byteLength(JSON.stringify(report)) > MAX_NORMALIZED_BYTES) fail('Normalized evidence exceeds the 10 MB processing limit.');
  return report;
}
export function buildReport(input) { return normalizeReport(input); }
export function parseReport(text, fileName = '') {
  if (typeof text !== 'string' || !text.trim()) fail('Choose a non-empty JSON or JSONL report.');
  const size = byteLength(text);
  if (size > MAX_BUNDLE_BYTES) fail('Report exceeds the 5 MB input limit or 20 MB portable-bundle limit.');
  const content = text.replace(/^\uFEFF/, '').trim();
  let input;
  if (/\.(jsonl|ndjson)$/i.test(fileName)) {
    if (size > MAX_BYTES) fail('Report exceeds the 5 MB limit.');
    const lines = content.split(/\r?\n/).filter(line => line.trim());
    if (lines.length > MAX_RECORDS) fail('Report exceeds the 1,000 evidence-record limit.');
    input = lines.map((line, index) => { try { return JSON.parse(line); } catch { return fail(`Invalid JSONL on line ${index + 1}.`); } });
  } else {
    try { input = JSON.parse(content); } catch { if (size > MAX_BYTES) fail('Report exceeds the 5 MB limit.'); fail('Invalid JSON. Use .jsonl for one record per line; Markdown samples alone are not supported.'); }
  }
  if (input?.manifest?.schemaVersion === 1 && object(input.files)) {
    const read = (name, maximum) => {
      const body = input.files[name]; if (body === undefined) return [];
      if (typeof body !== 'string' || byteLength(body) > MAX_NORMALIZED_BYTES) fail(`Invalid or oversized bundle file: ${name}.`);
      const lines = body.trim() ? body.trim().split(/\r?\n/) : [];
      if (lines.length > maximum) fail(`Too many rows in ${name}.`);
      return lines.map(line => { try { return JSON.parse(line); } catch { return fail(`Invalid JSONL in ${name}.`); } });
    };
    return normalizeReport({ title: input.manifest.title, records: read('evidence.jsonl', MAX_RECORDS),
      trace: { candidates: read('candidates.jsonl', MAX_TRACE), outcomes: read('outcomes.jsonl', MAX_TRACE), edges: read('edges.jsonl', MAX_TRACE) },
      ...(input.manifest.runSummary ? { runSummary: input.manifest.runSummary } : {}),
      omissions: input.manifest.omissions, warnings: input.manifest.warnings }, MAX_NORMALIZED_BYTES, true);
  }
  if (size > MAX_BYTES) fail('Report exceeds the 5 MB limit.');
  return buildReport(input);
}
export function filterRecords(report, { query = '', kind = '', contentStatus = '' } = {}) {
  const needle = clean(query, 500).toLowerCase();
  return report.records.filter(record => (!kind || kind === 'all' || record.kind === kind) && (!contentStatus || contentStatus === 'all' || record.contentStatus === contentStatus) && (!needle || `${record.title} ${record.url} ${record.source} ${record.content} ${Object.values(record.identifiers).flat().join(' ')}`.toLowerCase().includes(needle)));
}
export function buildDossier(report, domain) {
  const raw = clean(domain, 300);
  const url = publicUrl(raw.includes('://') ? raw : `https://${raw}`), parsed = new URL(url);
  if (parsed.pathname !== '/' || parsed.search) fail('Enter a company hostname, not a page URL.');
  const hostname = parsed.hostname;
  if (!report.records.some(record => record.hostname === hostname)) fail('This report has no evidence from that exact hostname.');
  const sections = { products: [], docs: [], announcements: [], roadmap: [], otherOfficial: [], independent: [], associatedUnverified: [], historical: [] };
  for (const record of report.records) {
    if (record.historical) { sections.historical.push(record); continue; }
    if (record.hostname !== hostname) {
      const relatedHost = record.hostname.endsWith(`.${hostname}`) || hostname.endsWith(`.${record.hostname}`);
      let associationHost = '';
      if (record.association?.domain) { try { const value = new URL(publicUrl(record.association.domain.includes('://') ? record.association.domain : `https://${record.association.domain}`)); if (value.pathname === '/' && !value.search) associationHost = value.hostname; } catch { /* An invalid affiliation claim cannot establish a domain association. */ } }
      const importedAssociation = associationHost === hostname && Boolean(record.association.claim || record.association.evidenceUrl);
      sections[importedAssociation || relatedHost ? 'associatedUnverified' : 'independent'].push(record); continue;
    }
    const path = new URL(record.url).pathname.toLowerCase();
    const explicit = ['products', 'docs', 'announcements', 'roadmap'].includes(record.section) ? record.section : '';
    const section = explicit || (/\/(docs?|documentation|api|reference)(\/|$)/.test(path) ? 'docs' : /\/(news|newsroom|press|announcements|changelog)(\/|$)/.test(path) ? 'announcements' : /\/roadmap(\/|$)/.test(path) ? 'roadmap' : /\/(products?|solutions)(\/|$)/.test(path) ? 'products' : 'otherOfficial');
    sections[section].push(record);
  }
  return { domain: hostname, sections, warnings: ['Official grouping means exact supplied hostname only; company ownership is not independently verified.', 'Subdomains and imported association claims remain unverified. Section labels may be inferred from URL paths.', 'External records come from the imported report scope; their relevance to this company is not independently verified.', 'Independent means a different unassociated hostname, not verified editorial independence. Only explicitly marked archives are historical.'] };
}
const jsonl = rows => rows.map(row => JSON.stringify(row)).join('\n') + (rows.length ? '\n' : '');
const csvCell = value => { let text = value == null ? '' : String(value); if (/^[\s]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text)) text = `'${text}`; return `"${text.replace(/"/g, '""')}"`; };
export function exportReport(report) {
  const urls = new Map();
  report.records.forEach(record => urls.set(record.urlId, record.url));
  [...report.trace.candidates, ...report.trace.outcomes].forEach(row => urls.set(row.urlId, row.url));
  report.trace.edges.forEach(row => { urls.set(row.sourceUrlId, row.sourceUrl); urls.set(row.targetUrlId, row.targetUrl); });
  const files = {
    'evidence.jsonl': jsonl(report.records),
    'evidence.csv': [['id', 'urlId', 'title', 'url', 'kind', 'contentStatus', 'publishedAt'], ...report.records.map(record => [record.id, record.urlId, record.title, record.url, record.kind, record.contentStatus, record.publishedAt])].map(row => row.map(csvCell).join(',')).join('\r\n') + '\r\n',
    'candidates.jsonl': jsonl(report.trace.candidates), 'outcomes.jsonl': jsonl(report.trace.outcomes), 'edges.jsonl': jsonl(report.trace.edges), 'relations.jsonl': jsonl(report.relations),
    'urls.jsonl': jsonl([...urls].map(([id, url]) => ({ id, url }))),
  };
  const manifest = { schemaVersion: 1, reportId: report.id, title: report.title, scope: 'Imported retained evidence only; no network collection or independent verification.', completeness: 'unknown', internetCoveragePercent: null,
    ...(report.runSummary ? { runSummary: report.runSummary } : {}),
    counts: report.stats, omissions: report.omissions, warnings: report.warnings,
    relationPolicy: 'Identifier matches do not merge records, prove causality, or establish independent evidence.',
    outcomeLinkPolicy: 'Outcome evidenceIds are same-URL references only, including for failed attempts; they do not establish which attempt produced evidence.',
    contentPolicy: 'Full means an imported assertion with retained body; metadata and unknown completeness stay explicit.', inputLimits: '5 MB raw reports; 20 MB portable bundles, with at most 10 MB reconstructed evidence and trace.',
    files: Object.entries(files).map(([name, content]) => ({ name, bytes: byteLength(content) })) };
  const bundle = { manifest, files };
  if (byteLength(JSON.stringify(bundle)) > MAX_BUNDLE_BYTES) fail('Portable bundle exceeds the 20 MB export limit. Export a smaller report.');
  return bundle;
}
