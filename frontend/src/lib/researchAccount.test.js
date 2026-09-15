import { buildReport, exportReport, parseReport } from './researchReport';
import { ACCOUNT_LIMITS, MAX_SAVED_REPORT_BYTES, ResearchAccountError, accountSnapshot, reopenSavedSnapshot, validateSavedMetadata, validateAccountListing, validateSavedReceipt, validateDeleteReceipt } from './researchAccount';

const ID = '12345678-1234-4234-8234-123456789abc';
const OTHER_ID = '12345678-1234-4234-8234-123456789abd';
const metadata = (extra = {}) => ({ id: ID, title: 'Stored synthetic research', saved_at: '2026-09-13T12:30:00.123456+00:00', byte_size: 100, ...extra });
const evidence = () => buildReport({ title: 'Stored synthetic research', records: [
  { id: 'source-a', url: 'https://example.org/paper', title: 'Synthetic HTML', kind: 'studies', content: 'Synthetic retained text, not a real finding.', contentStatus: 'full', doi: '10.9999/synthetic' },
  { id: 'source-b', url: 'https://example.net/paper.pdf', title: 'Synthetic PDF', kind: 'studies', doi: '10.9999/synthetic' },
], trace: { candidates: [{ url: 'https://example.org/paper', selected: true, reason: 'Synthetic reason' }], outcomes: [{ url: 'https://example.org/paper', status: 'completed' }], edges: [{ sourceUrl: 'https://example.org/search', targetUrl: 'https://example.org/paper' }] }, omissions: ['Synthetic fixture only.'], warnings: ['No live verification.'] });
const emptyRun = () => buildReport({
  id: '00000000-0000-4000-8000-000000000001', status: 'completed', title: 'Stored synthetic research',
  input: { urls: [], boards: [{ provider: 'lever', board: 'synthetic', limit: 20 }], pageLimit: 1, followLinks: false },
  progress: { total: 1, done: 1, pending: 0, inflight: 0, completed: 1, partial: 0, failed: 0, uncertain: 0 },
  result: { pages: [], jobs: [], records: [], incomplete: false,
    counts: { savedPages: 0, savedJobs: 0, structuredRecords: 0, successfulEmptyBoards: 1, selectedPages: 0, attemptedPages: 0, discoveredUrls: 0, notFetched: 0, frontierOmitted: 0, linksSkipped: 0, omittedRecords: 0, truncatedRecords: 0 },
    errors: [], warnings: [], searchSlices: [],
  },
});
const detailFor = (bundle, extra = {}) => ({ report: { ...metadata({ title: bundle.manifest.title, byte_size: new Blob([JSON.stringify(bundle)]).size }), bundle, ...extra } });
const listing = (reports = []) => ({ reports, used_bytes: reports.reduce((sum, report) => sum + report.byte_size, 0), limits: { ...ACCOUNT_LIMITS } });

describe('owner-scoped research snapshot boundary', () => {
  test.each([evidence, emptyRun])('round-trips the full normalized report without storing derived files', fixture => {
    const report = fixture(), snapshot = accountSnapshot(report);
    expect(Object.keys(snapshot.files)).toEqual(['evidence.jsonl', 'candidates.jsonl', 'outcomes.jsonl', 'edges.jsonl']);
    expect(snapshot.manifest.reportId).toBeUndefined();
    expect(snapshot.manifest.counts).toBeUndefined();
    expect(reopenSavedSnapshot(detailFor(snapshot), ID)).toEqual(report);
    expect(parseReport(JSON.stringify(snapshot), 'saved-report.json')).toEqual(report);
  });

  test('keeps read-only snapshots independent of account and ownership identifiers', () => {
    const snapshot = accountSnapshot(evidence());
    expect(Object.keys(snapshot)).toEqual(['manifest', 'files']);
    expect(snapshot.owner_id).toBeUndefined();
    expect(snapshot.accountId).toBeUndefined();
    const receipt = validateSavedReceipt({ report: metadata(), replay: false });
    expect(receipt).toEqual({ report: metadata(), replay: false });
    expect(validateSavedReceipt({ report: metadata(), replay: true }).replay).toBe(true);
  });
  test('a valid Unicode body crossing the 60000-unit limit remains UTF-8-safe in actual account snapshots', () => {
    const text = 'a'.repeat(59999);
    const report = buildReport({ title: 'Unicode source boundary', records: [{ url: 'https://example.org/unicode', content: `${text}😀` }] });
    const snapshot = accountSnapshot(report);
    expect(JSON.parse(snapshot.files['evidence.jsonl']).content).toBe(text);
    expect(reopenSavedSnapshot(detailFor(snapshot), ID)).toEqual(report);
  });

  test('rejects over-8 MiB account snapshots without lowering local portable limits', () => {
    const report = buildReport(Array.from({ length: 44 }, (_, index) => ({ url: `https://example.org/large-${index}`, title: 'Synthetic escaped text', content: '\\'.repeat(48000), contentStatus: 'unknown' })));
    const portable = JSON.stringify(exportReport(report));
    expect(new Blob([portable]).size).toBeGreaterThan(MAX_SAVED_REPORT_BYTES);
    expect(new Blob([portable]).size).toBeLessThan(20 * 1024 * 1024);
    expect(() => accountSnapshot(report)).toThrow(ResearchAccountError);
    try { accountSnapshot(report); } catch (error) { expect(error.code).toBe('ACCOUNT_REPORT_TOO_LARGE'); }
    expect(parseReport(portable).id).toBe(report.id);
  });

  test('validates complete account listings and exact configured caps', () => {
    expect(validateAccountListing(listing())).toEqual(listing());
    expect(validateAccountListing(listing([metadata()])).reports).toEqual([metadata()]);
    expect(ACCOUNT_LIMITS).toEqual({ max_reports: 20, max_report_bytes: 8388608, max_total_bytes: 10485760 });
  });

  test.each([
    { id: 'not-a-uuid' }, { title: '' }, { title: 'x'.repeat(501) }, { title: 'bad\u0000title' },
    { saved_at: '2026-02-30T10:00:00Z' }, { saved_at: '2026-09-13' }, { saved_at: '2026-09-13T25:00:00Z' },
    { byte_size: 0 }, { byte_size: MAX_SAVED_REPORT_BYTES + 1 }, { byte_size: 1.5 }, { owner_id: 'someone' },
  ])('rejects malformed or expanded listing metadata', change => {
    expect(() => validateSavedMetadata(metadata(change))).toThrow(ResearchAccountError);
  });

  test('accepts timezone-aware timestamps and canonicalizes UUID case only', () => {
    const valid = metadata({ id: ID.toUpperCase(), saved_at: '2024-02-29T12:00:00Z' });
    expect(validateSavedMetadata(valid)).toEqual({ ...valid, id: ID });
  });

  test('rejects inconsistent, duplicate, excessive and malformed listings', () => {
    const duplicate = listing([metadata(), metadata({ id: ID.toUpperCase() })]);
    expect(() => validateAccountListing(duplicate)).toThrow(ResearchAccountError);
    expect(() => validateAccountListing({ ...listing([metadata()]), used_bytes: 101 })).toThrow(ResearchAccountError);
    expect(() => validateAccountListing({ ...listing(), limits: { ...ACCOUNT_LIMITS, max_reports: 200 } })).toThrow(ResearchAccountError);
    expect(() => validateAccountListing({ ...listing(), reports: 'invalid' })).toThrow(ResearchAccountError);
    expect(() => validateAccountListing({ ...listing(), used_bytes: -1 })).toThrow(ResearchAccountError);
    expect(() => validateAccountListing({ ...listing(), owner_id: 'forged' })).toThrow(ResearchAccountError);
    expect(() => validateAccountListing(listing(Array.from({ length: 21 }, () => metadata())))).toThrow(ResearchAccountError);
    expect(() => validateAccountListing(listing([metadata({ byte_size: MAX_SAVED_REPORT_BYTES }), metadata({ id: OTHER_ID, byte_size: MAX_SAVED_REPORT_BYTES })]))).toThrow(ResearchAccountError);
  });

  test('requires the exact saved UUID and well-formed receipts', () => {
    const snapshot = accountSnapshot(evidence());
    expect(() => reopenSavedSnapshot(detailFor(snapshot), OTHER_ID)).toThrow(ResearchAccountError);
    expect(() => reopenSavedSnapshot(detailFor(snapshot), `/reports/${ID}`)).toThrow(ResearchAccountError);
    expect(() => reopenSavedSnapshot({ report: metadata() }, ID)).toThrow(ResearchAccountError);
    expect(() => reopenSavedSnapshot(detailFor(snapshot, { byte_size: MAX_SAVED_REPORT_BYTES + 1 }), ID)).toThrow(ResearchAccountError);
    expect(() => reopenSavedSnapshot(detailFor(snapshot, { title: 'Wrong metadata title' }), ID)).toThrow(ResearchAccountError);
    expect(() => validateSavedReceipt({ report: metadata(), replay: 'false' })).toThrow(ResearchAccountError);
    expect(() => validateSavedReceipt({ report: metadata(), replay: false, owner_id: 'other' })).toThrow(ResearchAccountError);
    expect(validateDeleteReceipt({ deleted: true })).toEqual({ deleted: true });
    expect(() => validateDeleteReceipt({ deleted: false })).toThrow(ResearchAccountError);
    expect(() => validateDeleteReceipt({ deleted: true, bundle: {} })).toThrow(ResearchAccountError);
  });

  test('reparses untrusted saved content instead of accepting supplied report objects', () => {
    const snapshot = accountSnapshot(evidence());
    snapshot.files['evidence.jsonl'] = JSON.stringify({ url: 'javascript:alert(1)', title: 'Unsafe saved content' });
    expect(() => reopenSavedSnapshot(detailFor(snapshot), ID)).toThrow(ResearchAccountError);
    snapshot.files['evidence.jsonl'] = '{"url":"https://example.org","__proto__":{"polluted":true}}';
    expect(() => reopenSavedSnapshot(detailFor(snapshot), ID)).toThrow(ResearchAccountError);
    const wrong = detailFor(accountSnapshot(evidence())); wrong.report.bundle.files['../secret'] = 'unsafe';
    expect(() => reopenSavedSnapshot(wrong, ID)).toThrow(ResearchAccountError);
    expect(() => accountSnapshot(null)).toThrow(ResearchAccountError);
    const badTitle = evidence(); badTitle.title = 'Invalid\naccount label';
    expect(() => accountSnapshot(badTitle)).toThrow(ResearchAccountError);
  });

  test('treats server byte_size as bounded quota metadata, not a browser JSON fingerprint', () => {
    const report = evidence(), snapshot = accountSnapshot(report), detail = detailFor(snapshot);
    detail.report.byte_size += 2;
    expect(reopenSavedSnapshot(detail, ID)).toEqual(report);
    const saved = metadata({ byte_size: detail.report.byte_size });
    expect(validateSavedReceipt({ report: saved, replay: false }).report.byte_size).toBe(detail.report.byte_size);
  });

  test('retains up to 1000 notes in account envelopes and rejects overflow without truncation', () => {
    const report = evidence();
    report.warnings = Array.from({ length: 1000 }, (_, index) => `Warning ${index}`);
    report.omissions = [...report.omissions, ...Array.from({ length: 1000 - report.omissions.length }, (_, index) => `Omission ${index}`)];
    const snapshot = accountSnapshot(report);
    expect(snapshot.manifest.warnings).toEqual(report.warnings);
    expect(snapshot.manifest.omissions).toEqual(report.omissions);
    expect(reopenSavedSnapshot(detailFor(snapshot), ID)).toEqual(report);
    report.warnings.push('Overflow');
    expect(() => accountSnapshot(report)).toThrow(ResearchAccountError);
    report.warnings.pop(); report.omissions.push('Overflow');
    expect(() => accountSnapshot(report)).toThrow(ResearchAccountError);
  });

  test('rejects oversized saved responses and unsafe envelopes before reopening', () => {
    const snapshot = accountSnapshot(evidence());
    snapshot.files['evidence.jsonl'] = 'x'.repeat(MAX_SAVED_REPORT_BYTES + 1);
    const detail = { report: { ...metadata(), bundle: snapshot } };
    expect(() => reopenSavedSnapshot(detail, ID)).toThrow(ResearchAccountError);
    expect(() => reopenSavedSnapshot({ ...detailFor(accountSnapshot(evidence())), accountId: 'forged' }, ID)).toThrow(ResearchAccountError);
  });
});
