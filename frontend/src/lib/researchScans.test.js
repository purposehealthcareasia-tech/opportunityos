import { parseReport } from './researchReport';
import { accountSnapshot } from './researchAccount';
import { newScanRequestKey, prepareScanInput, validateScanCapabilities, validateScanRun, validateScanList, validateScanResponse, validateScanStart, parseScanReport, describeScanFailure, ResearchScanError, SCAN_STATUSES, isScanActive, canCancelScan, canResumeScan, canImportScan } from './researchScans';

const id = 'a6623e49-2aa3-4311-8acf-127b32289b11';
const otherId = 'b6623e49-2aa3-4311-8acf-127b32289b22';
const capabilities = { available: true, reason: null, limits: { max_pages_per_run: 20, max_snapshot_bytes: 8388608, max_snapshots: 500 }, scope: 'Configured transport only; source health is not established.' };
function run(status = 'queued') {
  const progress = { total: 1, done: 0, pending: 0, inflight: 0, completed: 0, partial: 0, failed: 0, uncertain: 0 };
  if (['completed', 'partial', 'failed'].includes(status)) { progress.done = 1; progress[status] = 1; }
  else if (['running', 'cancel_requested'].includes(status)) progress.inflight = 1;
  else progress.pending = 1;
  return { id, status, input: { urls: ['https://example.org/evidence'], boards: [], pageLimit: 5, followLinks: false }, progress,
    createdAt: '2026-09-14T09:00:00Z', updatedAt: '2026-09-14T09:00:00Z',
    result: { incomplete: status !== 'completed', counts: { savedPages: ['completed', 'partial'].includes(status) ? 1 : 0, savedJobs: 0, structuredRecords: 0, successfulEmptyBoards: 0, selectedPages: 1, attemptedPages: 1, discoveredUrls: 1, notFetched: 0, frontierOmitted: 0, linksSkipped: 0, omittedRecords: 0, truncatedRecords: 0 } } };
}
function bundle(status = 'completed') {
  const completed = run(status);
  completed.result = { ...completed.result, pages: ['completed', 'partial'].includes(status) ? [{ url: 'https://example.org/evidence', title: 'Retained evidence', content: 'Synthetic source body.' }] : [], jobs: [], records: [], errors: status === 'failed' ? [{ code: 'SOURCE_TIMEOUT' }] : [], warnings: [], searchSlices: [] };
  return accountSnapshot(parseReport(JSON.stringify(completed)));
}

describe('Research scan boundary', () => {
  test('creates cryptographic request keys and fails closed without Web Crypto', () => {
    const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
    try {
      Object.defineProperty(globalThis, 'crypto', { configurable: true, value: { randomUUID: () => id } });
      expect(newScanRequestKey()).toBe(id);
      Object.defineProperty(globalThis, 'crypto', { configurable: true, value: { getRandomValues: bytes => { bytes.fill(1); return bytes; } } });
      expect(newScanRequestKey()).toBe('01010101-0101-4101-8101-010101010101');
      Object.defineProperty(globalThis, 'crypto', { configurable: true, value: undefined });
      expect(() => newScanRequestKey()).toThrow(/Secure request keys are unavailable/);
    } finally { if (original) Object.defineProperty(globalThis, 'crypto', original); else delete globalThis.crypto; }
  });
  test('normalizes explicit sources without enabling link traversal by default', () => {
    expect(prepareScanInput({ urls: 'https://example.org/evidence\nhttps://example.org/evidence', query: '  focused research  ', pageLimit: '5' })).toEqual({ urls: ['https://example.org/evidence'], query: 'focused research', pageLimit: 5, followLinks: false });
    expect(prepareScanInput({ query: 'research', pageLimit: 20, followLinks: true })).toEqual({ urls: [], query: 'research', pageLimit: 20, followLinks: true, maxDepth: 1 });
  });
  test('preserves distinct hash-routed pages and query strings in scan intent and run metadata', () => {
    const urls = ['https://example.org/?lang=en#/jobs/a', 'https://example.org/?lang=en#/jobs/b'];
    expect(prepareScanInput({ urls: [...urls, urls[0]] }).urls).toEqual(urls);
    expect(validateScanRun({ ...run(), input: { ...run().input, urls } }).input.urls).toEqual(urls);
  });
  test.each(['http://example.org/path', 'http://127.0.0.1', 'http://2130706433', 'https://localhost', 'https://host.internal/', 'https://host.lan', 'https://host.home', 'https://host.example', 'https://127.0.0.1.nip.io', 'https://localtest.me', 'https://host..org', 'https://-host.org', 'https://host.123', 'https://user:password@example.org', 'file:///etc/passwd', 'https://example.org:444/path', 'javascript:alert(1)'])('rejects unsupported source %s', url => {
    expect(() => prepareScanInput({ urls: url })).toThrow(ResearchScanError);
  });
  test('bounds URLs, queries and page limits before any request', () => {
    expect(() => prepareScanInput({ urls: Array.from({ length: 21 }, (_, i) => `https://example.org/${i}`) })).toThrow(/at most 20/);
    expect(() => prepareScanInput({ query: 'x'.repeat(401) })).toThrow(/400/);
    expect(() => prepareScanInput({ query: 'control\ncharacter' })).toThrow(/control/);
    for (const pageLimit of [0, 21, 1.5, true, '1e1', '']) expect(() => prepareScanInput({ query: 'research', pageLimit })).toThrow(/1 to 20/);
    expect(() => prepareScanInput({})).toThrow(/query or at least one/);
  });
  test('capabilities describe configuration and reject inconsistent availability', () => {
    expect(validateScanCapabilities(capabilities)).toEqual(capabilities);
    expect(validateScanCapabilities({ ...capabilities, available: false, reason: 'disabled' }).available).toBe(false);
    expect(() => validateScanCapabilities({ ...capabilities, reason: 'configuration_required' })).toThrow();
    expect(() => validateScanCapabilities({ ...capabilities, limits: { ...capabilities.limits, max_pages_per_run: 1000 } })).toThrow();
  });
  test.each(SCAN_STATUSES)('validates actual engine status %s and ignores raw evidence/owner fields', status => {
    const raw = { ...run(status), owner: 'private-owner', units: [{ content: 'not retained in UI metadata' }] };
    const result = validateScanRun(raw, id);
    expect(result.status).toBe(status);
    expect(result.owner).toBeUndefined();
    expect(result.units).toBeUndefined();
  });
  test('binds responses to the requested run and checks coherent progress', () => {
    expect(() => validateScanResponse({ run: run() }, otherId)).toThrow();
    expect(() => validateScanRun({ ...run(), status: 'interrupted' })).toThrow();
    expect(() => validateScanRun({ ...run(), progress: { ...run().progress, done: 1 } })).toThrow();
    expect(() => validateScanRun({ ...run(), progress: { ...run().progress, total: 100000 } })).toThrow();
    expect(() => validateScanRun({ ...run(), input: { ...run().input, query: 'secret\ncontrol' } })).toThrow();
    expect(() => validateScanRun({ ...run(), createdAt: 'not a date' })).toThrow();
  });
  test('bounds and de-duplicates the run list and validates replay receipts', () => {
    expect(validateScanList({ runs: [run()] })).toHaveLength(1);
    expect(() => validateScanList({ runs: [run(), run()] })).toThrow();
    expect(() => validateScanList({ runs: Array.from({ length: 101 }, () => run()) })).toThrow();
    expect(validateScanStart({ run: run(), replay: false }).replay).toBe(false);
    expect(() => validateScanStart({ run: run(), replay: 'yes' })).toThrow();
  });
  test('exposes only supported lifecycle actions', () => {
    expect(isScanActive(run('cancel_requested'))).toBe(true);
    expect(isScanActive(run('paused'))).toBe(false);
    expect(canCancelScan(run('running'))).toBe(true);
    expect(canCancelScan(run('cancel_requested'))).toBe(false);
    expect(canResumeScan(run('paused'))).toBe(true);
    expect(canResumeScan(run('failed'))).toBe(false);
    expect(canImportScan(run('partial'))).toBe(true);
    expect(canImportScan(run('failed'))).toBe(true);
    expect(canImportScan(run('cancelled'))).toBe(true);
  });
  test('reopens an inert report through the real parser and binds its run identity', () => {
    const value = bundle(), report = parseScanReport(value, id);
    expect(report.runSummary.id).toBe(id);
    expect(report.records[0].content).toBe('Synthetic source body.');
    expect(() => parseScanReport(value, otherId)).toThrow();
    expect(() => parseScanReport({ ...value, manifest: { ...value.manifest, runSummary: { ...value.manifest.runSummary, status: 'running' } } }, id)).toThrow();
    expect(() => parseScanReport({ manifest: {}, files: {} }, id)).toThrow();
  });
  test.each(['completed', 'partial', 'failed', 'cancelled'])('retains report diagnostics for stable terminal status %s', status => {
    const report = parseScanReport(bundle(status), id);
    expect(report.runSummary.status).toBe(status);
    if (status === 'failed') expect(report.runSummary.errors[0].code).toBe('SOURCE_TIMEOUT');
    if (['failed', 'cancelled'].includes(status)) expect(report.records).toHaveLength(0);
  });
  test('never exposes backend errors and distinguishes uncertain writes from reads', () => {
    const timeout = { message: 'SECRET', code: 'ECONNABORTED' };
    expect(describeScanFailure(timeout, 'start').uncertain).toBe(true);
    expect(describeScanFailure(timeout, 'status').uncertain).toBe(false);
    const denied = describeScanFailure({ response: { status: 401, data: { detail: { message: 'SECRET' } } } }, 'start');
    expect(denied.sessionExpired).toBe(true);
    expect(JSON.stringify(denied)).not.toContain('SECRET');
    expect(describeScanFailure({ response: { status: 429, data: { detail: { uncertain: true } } } }, 'start').uncertain).toBe(true);
    expect(describeScanFailure(new ResearchScanError('SCAN_INVALID_INPUT', 'Bad input.'), 'read').message).toBe('Bad input.');
  });
});
