import { exportReport, parseReport } from './researchReport';

export const MAX_SAVED_REPORT_BYTES = 8 * 1024 * 1024;
export const ACCOUNT_LIMITS = Object.freeze({ max_reports: 20, max_report_bytes: MAX_SAVED_REPORT_BYTES, max_total_bytes: 10 * 1024 * 1024 });
const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const FILES = ['evidence.jsonl', 'candidates.jsonl', 'outcomes.jsonl', 'edges.jsonl'];
const META_FIELDS = ['id', 'title', 'saved_at', 'byte_size'];
const plain = value => value !== null && typeof value === 'object' && !Array.isArray(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value));
const bytes = text => new Blob([text]).size;
const exactKeys = (value, names) => plain(value) && Reflect.ownKeys(value).length === names.length && names.every(name => Object.prototype.hasOwnProperty.call(value, name));
const validTitle = value => typeof value === 'string' && Boolean(value.trim()) && value.length <= 500 && !Array.from(value).some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127);

export class ResearchAccountError extends Error {
  constructor(code, message) { super(message); this.name = 'ResearchAccountError'; this.code = code; }
}
function invalidResponse() { throw new ResearchAccountError('ACCOUNT_INVALID_RESPONSE', 'Fynd returned an invalid saved-report response. Your current report has not been changed.'); }
function invalidSnapshot() { throw new ResearchAccountError('ACCOUNT_INVALID_SNAPSHOT', 'This research snapshot is invalid or unsupported. Your current report has not been changed.'); }
function tooLarge() { throw new ResearchAccountError('ACCOUNT_REPORT_TOO_LARGE', 'This report exceeds the 8 MiB account-save limit. You can still use the local report and download it.'); }
function reportUuid(value) {
  if (typeof value !== 'string' || !UUID.test(value)) throw new ResearchAccountError('ACCOUNT_INVALID_REPORT_ID', 'A valid saved-report ID is required.');
  return value.toLowerCase();
}
function validTimestamp(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return false;
  const year = Number(value.slice(0, 4)), month = Number(value.slice(5, 7)), day = Number(value.slice(8, 10));
  const days = [31, (year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month < 1 || month > 12 || day < 1 || day > days[month - 1] || Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59) return false;
  return Number.isFinite(Date.parse(value));
}
export function validateSavedMetadata(value) {
  if (!exactKeys(value, META_FIELDS) || typeof value.id !== 'string' || !UUID.test(value.id) || !validTitle(value.title) || !validTimestamp(value.saved_at) ||
      !Number.isSafeInteger(value.byte_size) || value.byte_size < 1 || value.byte_size > MAX_SAVED_REPORT_BYTES) invalidResponse();
  return { id: value.id.toLowerCase(), title: value.title, saved_at: value.saved_at, byte_size: value.byte_size };
}

// These are source files, not a second evidence schema. The existing parser
// regenerates derived relations, URL tables, CSV and statistics when reopened.
function snapshotText(bundle) {
  if (!exactKeys(bundle, ['manifest', 'files']) || !plain(bundle.manifest) || !exactKeys(bundle.files, FILES)) invalidSnapshot();
  const manifestKeys = ['schemaVersion', 'title', 'omissions', 'warnings', ...(Object.prototype.hasOwnProperty.call(bundle.manifest, 'runSummary') ? ['runSummary'] : [])];
  if (!exactKeys(bundle.manifest, manifestKeys) || bundle.manifest.schemaVersion !== 1 || !validTitle(bundle.manifest.title) ||
      !Array.isArray(bundle.manifest.omissions) || !Array.isArray(bundle.manifest.warnings) || bundle.manifest.omissions.length > 1000 || bundle.manifest.warnings.length > 1000 ||
      [...bundle.manifest.omissions, ...bundle.manifest.warnings].some(value => typeof value !== 'string' || value.length > 1000)) invalidSnapshot();
  for (const name of FILES) {
    if (typeof bundle.files[name] !== 'string') invalidSnapshot();
    if (bytes(bundle.files[name]) > MAX_SAVED_REPORT_BYTES) tooLarge();
  }
  let text;
  try { text = JSON.stringify(bundle); } catch { invalidSnapshot(); }
  if (bytes(text) > MAX_SAVED_REPORT_BYTES) tooLarge();
  return text;
}
export function accountSnapshot(report) {
  let exported;
  try { exported = exportReport(report); } catch { invalidSnapshot(); }
  const { manifest, files } = exported;
  const bundle = {
    manifest: { schemaVersion: 1, title: manifest.title, omissions: manifest.omissions, warnings: manifest.warnings, ...(manifest.runSummary ? { runSummary: manifest.runSummary } : {}) },
    files: Object.fromEntries(FILES.map(name => [name, files[name]])),
  };
  snapshotText(bundle);
  return bundle;
}

export function validateAccountListing(value) {
  if (!exactKeys(value, ['reports', 'used_bytes', 'limits']) || !Array.isArray(value.reports) || value.reports.length > ACCOUNT_LIMITS.max_reports ||
      !exactKeys(value.limits, Object.keys(ACCOUNT_LIMITS)) || Object.entries(ACCOUNT_LIMITS).some(([name, limit]) => value.limits[name] !== limit) ||
      !Number.isSafeInteger(value.used_bytes) || value.used_bytes < 0 || value.used_bytes > ACCOUNT_LIMITS.max_total_bytes) invalidResponse();
  const reports = value.reports.map(validateSavedMetadata);
  if (new Set(reports.map(report => report.id)).size !== reports.length || reports.reduce((sum, report) => sum + report.byte_size, 0) !== value.used_bytes) invalidResponse();
  return { reports, used_bytes: value.used_bytes, limits: { ...ACCOUNT_LIMITS } };
}
export function validateSavedReceipt(value) {
  if (!exactKeys(value, ['report', 'replay']) || typeof value.replay !== 'boolean') invalidResponse();
  return { report: validateSavedMetadata(value.report), replay: value.replay };
}
export function validateDeleteReceipt(value) {
  if (!exactKeys(value, ['deleted']) || value.deleted !== true) invalidResponse();
  return { deleted: true };
}
export function reopenSavedSnapshot(detail, expectedUuid) {
  const expected = reportUuid(expectedUuid);
  if (!exactKeys(detail, ['report']) || !exactKeys(detail.report, [...META_FIELDS, 'bundle'])) invalidResponse();
  const metadata = validateSavedMetadata(Object.fromEntries(META_FIELDS.map(name => [name, detail.report[name]])));
  if (metadata.id !== expected) invalidResponse();
  const text = snapshotText(detail.report.bundle);
  // byte_size is the server's canonical JSON quota measurement. Equivalent
  // Python/JavaScript numeric encodings need not have identical byte lengths.
  if (detail.report.bundle.manifest.title !== metadata.title) invalidResponse();
  try { return parseReport(text, 'saved-report.json'); } catch { invalidSnapshot(); }
}
