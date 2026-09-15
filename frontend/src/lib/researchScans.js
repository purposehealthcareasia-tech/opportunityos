import { parseReport } from './researchReport';

export const SCAN_STATUSES = Object.freeze(['queued', 'running', 'paused', 'cancel_requested', 'completed', 'partial', 'failed', 'cancelled']);
export const SCAN_POLL_INTERVAL_MS = 5000;
export const SCAN_MAX_POLLS = 60;
const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const plain = value => value !== null && typeof value === 'object' && !Array.isArray(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value));
const integer = (value, max = 1000000) => Number.isSafeInteger(value) && value >= 0 && value <= max;
const controls = value => Array.from(value).some(character => { const code = character.charCodeAt(0); return code < 32 || (code >= 127 && code <= 159); });
export class ResearchScanError extends Error {
  constructor(code, message) { super(message); this.name = 'ResearchScanError'; this.code = code; }
}
const invalid = () => { throw new ResearchScanError('SCAN_INVALID_RESPONSE', 'Fynd returned an invalid scan response. No research report was imported.'); };
const badInput = message => { throw new ResearchScanError('SCAN_INVALID_INPUT', message); };

export function scanId(value) {
  if (typeof value !== 'string' || !UUID.test(value)) invalid();
  return value.toLowerCase();
}
export function newScanRequestKey() {
  try {
    const secure = typeof window === 'undefined' ? undefined : window.crypto;
    if (typeof secure?.randomUUID === 'function') {
      const key = secure.randomUUID();
      if (typeof key === 'string' && UUID.test(key)) return key.toLowerCase();
      throw new Error('Invalid secure UUID');
    }
    if (typeof secure?.getRandomValues !== 'function') throw new Error('Secure randomness unavailable');
    const bytes = new Uint8Array(16);
    secure.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  } catch { throw new ResearchScanError('SCAN_KEY_UNAVAILABLE', 'Secure request keys are unavailable. Open Fynd in a supported secure browser before starting a scan.'); }
}
function publicUrl(value) {
  if (typeof value !== 'string' || !value || value.length > 2048 || controls(value) || /[\s\\]/.test(value)) badInput('Use absolute public website URLs, one per line.');
  let url;
  try { url = new URL(value); } catch { badInput('Use absolute public website URLs, one per line.'); }
  const host = url.hostname.toLowerCase();
  if (url.protocol !== 'https:' || url.username || url.password || url.port || !host.includes('.') || host.endsWith('.') || !/^[a-z0-9.-]+$/.test(host) || host.split('.').some(part => !part || part.length > 63 || part.startsWith('-') || part.endsWith('-')) || /^(?:[0-9]+|0x[a-f0-9]+)$/.test(host.split('.').pop()) || /(^|\.)(localhost|local|internal|intranet|lan|home|test|invalid|example|onion)$/.test(host) || /(^|\.)(nip\.io|sslip\.io|localtest\.me)$/.test(host)) badInput('Use public HTTPS URLs. Private addresses, credentials, custom ports and unsupported URL schemes are not accepted.');
  // Fragments can identify distinct routes in client-rendered sites. Preserve
  // them in collection intent; only the engine owns source normalization.
  return url.href;
}

export function prepareScanInput({ urls = '', query = '', pageLimit = 5, followLinks = false } = {}) {
  if ((typeof urls !== 'string' && !Array.isArray(urls)) || typeof query !== 'string' || typeof followLinks !== 'boolean') badInput('The scan input is invalid.');
  const lines = typeof urls === 'string' ? urls.split(/\r?\n/).map(value => value.trim()).filter(Boolean) : urls;
  if (lines.length > 20) badInput('Choose at most 20 source URLs per scan.');
  if (query.length > 400 || controls(query)) badInput('Use a query of at most 400 characters without control characters.');
  const pages = typeof pageLimit === 'string' && /^\d+$/.test(pageLimit) ? Number(pageLimit) : pageLimit;
  if (!Number.isInteger(pages) || pages < 1 || pages > 20) badInput('Choose a page limit from 1 to 20.');
  const normalized = [...new Set(lines.map(publicUrl))], text = query.trim();
  if (!normalized.length && !text) badInput('Add a search query or at least one public source URL.');
  return { urls: normalized, ...(text ? { query: text } : {}), pageLimit: pages, followLinks, ...(followLinks ? { maxDepth: 1 } : {}) };
}

export function validateScanCapabilities(value) {
  if (!plain(value) || typeof value.available !== 'boolean' || ![null, 'disabled', 'configuration_required'].includes(value.reason) ||
      !plain(value.limits) || value.limits.max_pages_per_run !== 20 || value.limits.max_snapshot_bytes !== 8388608 || value.limits.max_snapshots !== 500 ||
      typeof value.scope !== 'string' || value.scope.length > 1000 || controls(value.scope) || (value.available && value.reason !== null) || (!value.available && value.reason === null)) invalid();
  return { available: value.available, reason: value.reason, limits: { ...value.limits }, scope: value.scope };
}

export function validateScanRun(value, expectedId) {
  if (!plain(value)) invalid();
  const id = scanId(value.id);
  if ((expectedId && id !== scanId(expectedId)) || !SCAN_STATUSES.includes(value.status) || !plain(value.input) || !plain(value.progress) || !plain(value.result) || !plain(value.result.counts) || typeof value.result.incomplete !== 'boolean') invalid();
  const progress = {};
  for (const name of ['total', 'done', 'pending', 'inflight', 'completed', 'partial', 'failed', 'uncertain']) {
    if (!integer(value.progress[name], 27)) invalid();
    progress[name] = value.progress[name];
  }
  if (progress.done !== progress.completed + progress.partial + progress.failed + progress.uncertain || progress.total !== progress.done + progress.pending + progress.inflight) invalid();
  if (!Array.isArray(value.input.urls) || value.input.urls.length > 20 || !integer(value.input.pageLimit, 20) || value.input.pageLimit < 1 || typeof value.input.followLinks !== 'boolean') invalid();
  const input = { urls: [], pageLimit: value.input.pageLimit, followLinks: value.input.followLinks };
  try { input.urls = value.input.urls.map(publicUrl); } catch { invalid(); }
  if (value.input.query !== undefined) {
    if (typeof value.input.query !== 'string' || !value.input.query.trim() || value.input.query.length > 400 || controls(value.input.query)) invalid();
    input.query = value.input.query;
  }
  const counts = {};
  for (const name of ['savedPages', 'savedJobs', 'structuredRecords']) {
    if (!integer(value.result.counts[name])) invalid();
    counts[name] = value.result.counts[name];
  }
  const timestamps = {};
  for (const name of ['createdAt', 'updatedAt']) {
    if (typeof value[name] !== 'string' || value[name].length > 40 || !/^\d{4}-\d\d-\d\dT/.test(value[name]) || !Number.isFinite(Date.parse(value[name]))) invalid();
    timestamps[name] = value[name];
  }
  // Deliberately omit raw source bodies, event logs, owner fields and unknown keys.
  return { id, status: value.status, input, progress, result: { counts, incomplete: value.result.incomplete }, ...timestamps };
}

export function validateScanList(value) {
  if (!plain(value) || !Array.isArray(value.runs) || value.runs.length > 100) invalid();
  const runs = value.runs.map(run => validateScanRun(run));
  if (new Set(runs.map(run => run.id)).size !== runs.length) invalid();
  return runs;
}
export function validateScanResponse(value, expectedId) {
  if (!plain(value)) invalid();
  return validateScanRun(value.run, expectedId);
}
export function validateScanStart(value) {
  if (!plain(value) || typeof value.replay !== 'boolean') invalid();
  return { replay: value.replay, run: validateScanRun(value.run) };
}
export const isScanActive = run => ['queued', 'running', 'cancel_requested'].includes(run?.status);
export const canCancelScan = run => ['queued', 'running', 'paused'].includes(run?.status);
export const canResumeScan = run => run?.status === 'paused';
export const canImportScan = run => ['completed', 'partial', 'failed', 'cancelled'].includes(run?.status);

export function parseScanReport(bundle, expectedId) {
  const id = scanId(expectedId);
  if (!plain(bundle) || !plain(bundle.manifest) || !plain(bundle.files)) invalid();
  let text;
  try { text = JSON.stringify(bundle); } catch { invalid(); }
  if (new Blob([text]).size > 8 * 1024 * 1024 || bundle.manifest.runSummary?.id !== id) invalid();
  let report;
  try { report = parseReport(text, 'collider-scan.json'); } catch { invalid(); }
  if (report.runSummary?.id !== id || !canImportScan(report.runSummary)) invalid();
  return report;
}

export function describeScanFailure(error, operation = 'read') {
  const status = error?.response?.status;
  const mutation = ['start', 'cancel', 'resume'].includes(operation);
  const uncertain = mutation && (error?.response?.data?.detail?.uncertain === true || (error instanceof ResearchScanError && error.code === 'SCAN_INVALID_RESPONSE') || !Number.isInteger(status) || status >= 500 || status === 409);
  if (status === 401) return { sessionExpired: true, uncertain: false, message: 'Your Fynd session has expired. Scan details were cleared. Sign in again, then check availability.' };
  if (error instanceof ResearchScanError) return { sessionExpired: false, uncertain, message: uncertain ? 'The scan request could not be confirmed. It may have started; refresh saved scans or retry the same request.' : error.message };
  const messages = {
    400: 'Check the source URLs, query and page limit before retrying.',
    403: 'Fynd did not authorize this action. Check your account permissions and required consent.',
    404: 'This scan is unavailable. Refresh the saved scan list.',
    409: 'The scan request could not be reconciled. Check saved scans before changing the request.',
    413: 'The scan request or retained report exceeds a storage limit. Use a smaller scan.',
    422: 'Check the source URLs, query and page limit before retrying.',
    429: 'A scan quota or request limit was reached. Wait, then check the scan status.',
    503: 'Scanning is unavailable or not configured. No successful scan is being claimed.',
  };
  return { sessionExpired: false, uncertain, message: uncertain ? 'The scan request could not be confirmed. It may have completed on the server; check saved scans before retrying.' : messages[status] || 'The scan service could not be reached. Your open research report is unchanged.' };
}
