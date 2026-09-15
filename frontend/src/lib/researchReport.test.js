import { buildReport, parseReport, filterRecords, buildDossier, exportReport } from './researchReport';

const row = (extra = {}) => ({ url: 'https://example.com/paper', title: 'A result', ...extra });
const emptyColliderRun = () => ({
  id: '00000000-0000-4000-8000-000000000001', status: 'partial',
  input: { urls: [], boards: [], query: 'Synthetic zero-result run', pageLimit: 1, followLinks: false },
  createdAt: '2026-09-11T00:00:00Z', updatedAt: '2026-09-11T00:01:00Z', finishedAt: '2026-09-11T00:01:00Z',
  progress: { total: 2, done: 2, pending: 0, inflight: 0, completed: 0, partial: 1, failed: 1, uncertain: 0 },
  units: [{ id: 'page-unit', kind: 'page', status: 'failed', input: { url: 'https://example.org/no-evidence' }, error: 'SOURCE_TIMEOUT' }],
  edges: [{ sourceUrl: 'https://example.org/search', targetUrl: 'https://example.org/no-evidence', type: 'imported-link' }],
  result: {
    pages: [], jobs: [], records: [], incomplete: true,
    counts: { savedPages: 0, savedJobs: 0, structuredRecords: 0, successfulEmptyBoards: 0, selectedPages: 1, attemptedPages: 1, discoveredUrls: 1, notFetched: 1, frontierOmitted: 0, linksSkipped: 0, omittedRecords: 0, truncatedRecords: 0 },
    coverage: { percent: null, denominator: null, scope: 'Synthetic bounded sources only.' },
    selectionPriority: 'Synthetic explicit-source ordering.',
    errors: [{ code: 'SOURCE_TIMEOUT', unitId: 'page-unit', url: 'https://example.org/no-evidence' }],
    warnings: [{ code: 'PARSER_WARNING', unitId: 'page-unit' }],
    searchSlices: [{ unitId: 'search-unit', query: 'Synthetic zero-result run', status: 'partial', returned: 1,
      results: [{ url: 'https://example.org/no-evidence', title: 'Synthetic candidate without retained evidence' }],
      providers: [{ id: 'synthetic', status: 'ok', returned: 1 }, { id: 'synthetic-disabled', status: 'unconfigured', code: 'PROVIDER_UNCONFIGURED', returned: 0 }] }],
  },
});
describe('local research report tools', () => {
  test('strips non-printing controls from text and rejects them in source URLs', () => {
    const report = buildReport([row({ content: '\u0000A\tB\nC\rD\u0008\u007f' })]);
    expect(report.records[0].content).toBe('A\tB\nC\rD');
    ['https://example.com/\u0000bad', 'https://example.com/\nbad', 'https://example.com/\\bad'].forEach(url => {
      expect(() => buildReport([row({ url })])).toThrow(/unsafe URL/);
    });
  });
  test('does not split valid Unicode pairs at text limits or repair invalid source surrogates', () => {
    const body = 'a'.repeat(59999), title = 't'.repeat(499);
    const report = buildReport([row({ content: `${body}😀`, title: `${title}😀` })]);
    expect(report.records[0].content).toBe(body);
    expect(report.records[0].title).toBe(title);
    expect(report.records[0].contentStatus).toBe('partial');
    expect(buildReport([row({ content: '\ud83d' })]).records[0].content.charCodeAt(0)).toBe(0xd83d);
  });
  test('imports bounded JSON and JSONL without fetching', () => {
    expect(parseReport(JSON.stringify([row()])).records).toHaveLength(1);
    expect(parseReport(`${JSON.stringify(row())}\n${JSON.stringify(row({ url: 'https://example.org/study' }))}`, 'evidence.jsonl').records).toHaveLength(2);
    expect(() => parseReport('# Markdown only', 'report.md')).toThrow(/Markdown/);
    expect(() => parseReport('{bad}', 'a.json')).toThrow(/Invalid JSON/);
    expect(() => parseReport('x'.repeat(5 * 1024 * 1024 + 1))).toThrow(/5 MB/);
    expect(() => buildReport(Array.from({ length: 1001 }, () => row()))).toThrow(/1,000/);
  });
  test('rejects dangerous object keys, malformed fields and unsafe URLs', () => {
    expect(() => parseReport('{"records":[],"__proto__":{"polluted":true}}')).toThrow(/Unsafe/);
    expect(() => buildReport({ records: 'bad' })).toThrow(/array/);
    ['javascript:alert(1)', 'https://user:secret@example.com', 'http://127.0.0.1', 'https://localhost', 'http://169.254.169.254', 'https://example.com:8443', 'https://example.internal'].forEach(url => {
      expect(() => buildReport([row({ url })])).toThrow();
    });
  });
  test('does not claim full content merely because text exists', () => {
    const report = buildReport([
      row(), row({ text: 'some retained body' }), row({ snippet: 'excerpt' }),
      row({ content: 'body', contentStatus: 'full' }), row({ content: 'body', contentStatus: 'full', truncated: true }), row({ contentStatus: 'full' }),
    ]);
    expect(report.records.map(record => record.contentStatus)).toEqual(['metadata-only', 'unknown', 'partial', 'full', 'partial', 'metadata-only']);
    expect(report.warnings.join(' ')).toMatch(/downgraded/);
  });
  test('preserves separate evidence records and deterministic identities', () => {
    const input = [row(), row(), row({ title: 'Another source object' })], first = buildReport(input), second = buildReport(input);
    expect(first.id).toBe(second.id);
    expect(new Set(first.records.map(record => record.id)).size).toBe(3);
    expect(first.records[0].urlId).toBe(first.records[1].urlId);
  });
  test('links explicit DOI and trial identifiers without merging or counting independence', () => {
    const report = buildReport([
      row({ doi: '10.1234/ABC', trialId: 'NCT01234567', kind: 'paper' }),
      row({ url: 'https://doi.org/10.1234/abc', kind: 'study' }),
      row({ url: 'https://clinicaltrials.gov/study/NCT01234567', kind: 'trial' }),
    ]);
    expect(report.records).toHaveLength(3);
    expect(report.relations.map(relation => relation.type).sort()).toEqual(['shared-publication-identifier', 'shared-trial-reference']);
    expect(report.relations.every(relation => relation.independentEvidence === 'not-established')).toBe(true);
  });
  test('does not link conflicting publication IDs or invented free-text identifiers', () => {
    const report = buildReport([
      row({ doi: '10.1234/abc', pmid: '111' }),
      row({ url: 'https://example.org/study', doi: '10.1234/abc', pmid: '222' }),
      row({ url: 'https://example.net/news', text: 'Someone mentioned doi:10.1234/abc' }),
    ]);
    expect(report.relations).toHaveLength(0);
    expect(report.warnings.join(' ')).toMatch(/Conflicting/);
  });
  test('supports conservative Collider summaries and explicit page-unit outcomes', () => {
    const report = buildReport({ id: 'run', units: [{ id: 'u1', kind: 'page', input: { url: 'https://example.com/a' }, status: 'completed' }], result: {
      pages: [row({ url: 'https://example.com/a', id: 'known', contentHash: '123' })],
      records: [{ sourceUrl: 'https://example.com/a', types: ['NewsArticle'], data: { headline: 'News' } }],
      discovery: { results: [{ url: 'https://example.com/a', title: 'A', sources: [{ provider: 'brave', rank: 1, kind: 'search' }], score: 0.02 }] }, counts: { frontierOmitted: 2 },
    } });
    expect(report.records).toHaveLength(2);
    expect(report.records.every(record => record.contentStatus === 'metadata-only')).toBe(true);
    expect(report.records[0].kind).toBe('news');
    expect(report.trace.outcomes[0].status).toBe('completed');
    expect(report.trace.candidates[0].selected).toBe(null);
    expect(report.trace.candidates[0].sources[0].provider).toBe('brave');
    expect(report.trace.candidates[0].scoreBasis).toMatch(/not a truth/);
    expect(report.trace.edges).toHaveLength(0);
    expect(report.omissions.join(' ')).toMatch(/not restored/);
  });
  test('retains a valid zero-result Collider run with summary, diagnostics and trace', () => {
    const input = emptyColliderRun(), report = parseReport(JSON.stringify(input), 'lynk-run.json');
    expect(report.records).toEqual([]);
    expect(report.stats).toEqual({ records: 0, domains: 0, relations: 0, candidates: 1, outcomes: 1, edges: 1 });
    expect(report.title).toBe(input.input.query);
    expect(report.runSummary.id).toBe(input.id);
    expect(report.runSummary.status).toBe('partial');
    expect(report.runSummary.progress).toEqual(input.progress);
    expect(report.runSummary.counts).toEqual(input.result.counts);
    expect(report.runSummary.errors[0].code).toBe('SOURCE_TIMEOUT');
    expect(report.runSummary.warnings[0].code).toBe('PARSER_WARNING');
    expect(report.runSummary.searchSlices[0].providers[1].code).toBe('PROVIDER_UNCONFIGURED');
    expect(report.trace.outcomes[0].evidenceIds).toEqual([]);
    expect(filterRecords(report)).toEqual([]);
    expect(() => buildDossier(report, 'example.org')).toThrow(/no evidence/);
  });
  test('retains completed empty-board and queued zero-result observations without inventing evidence', () => {
    const completed = emptyColliderRun();
    completed.status = 'completed';
    completed.input = { urls: [], boards: [{ provider: 'lever', board: 'synthetic', limit: 20 }], pageLimit: 1, followLinks: false };
    completed.progress = { total: 1, done: 1, pending: 0, inflight: 0, completed: 1, partial: 0, failed: 0, uncertain: 0 };
    completed.units = []; completed.edges = [];
    completed.result = { ...completed.result, incomplete: false, errors: [], warnings: [], searchSlices: [], counts: Object.fromEntries(Object.keys(completed.result.counts).map(key => [key, key === 'successfulEmptyBoards' ? 1 : 0])) };
    const report = buildReport(completed);
    expect(report.records).toHaveLength(0);
    expect(report.runSummary.status).toBe('completed');
    expect(report.runSummary.counts.successfulEmptyBoards).toBe(1);
    expect(exportReport(report).manifest.internetCoveragePercent).toBe(null);
    const queued = emptyColliderRun();
    queued.status = 'queued'; queued.finishedAt = null;
    queued.progress = { total: 1, done: 0, pending: 1, inflight: 0, completed: 0, partial: 0, failed: 0, uncertain: 0 };
    queued.units = []; queued.edges = [];
    queued.result.errors = []; queued.result.warnings = []; queued.result.searchSlices = [];
    queued.result.counts = Object.fromEntries(Object.keys(queued.result.counts).map(key => [key, 0]));
    expect(buildReport(queued).runSummary.status).toBe('queued');
  });
  test('imports a complete gateway-shaped empty-board run envelope', () => {
    const at = '2026-09-11T00:00:00.000Z', runId = '00000000-0000-4000-8000-000000000010', unitId = '00000000-0000-4000-8000-000000000011';
    const board = { provider: 'lever', board: 'synthetic', limit: 20 };
    const run = {
      id: runId, input: { urls: [], boards: [board], pageLimit: 5, followLinks: false }, status: 'completed',
      createdAt: at, updatedAt: at, startedAt: at, finishedAt: at, cancelRequestedAt: null, allocatedPages: 0,
      units: [{ id: unitId, kind: 'board', input: board, status: 'completed', startedAt: at, finishedAt: at,
        result: { status: 'completed', pages: [], jobs: [], records: [], errors: [], warnings: [], omittedRecords: 0, truncatedRecords: 0,
          boards: [{ ...board, status: 'ok', returned: 0, omitted: 0, truncated: false }] } }],
      events: [{ at, type: 'queued' }, { at, type: 'unit_completed', unitId }, { at, type: 'completed' }], eventsDropped: 0,
      progress: { total: 1, done: 1, pending: 0, inflight: 0, completed: 1, partial: 0, failed: 0, uncertain: 0 },
      result: {
        counts: { savedPages: 0, savedJobs: 0, structuredRecords: 0, successfulEmptyBoards: 1, selectedPages: 0, attemptedPages: 0, discoveredUrls: 0, notFetched: 0, frontierOmitted: 0, linksSkipped: 0, omittedRecords: 0, truncatedRecords: 0 },
        coverage: { percent: null, denominator: null, scope: 'Only explicit sources and bounded selected pages; pending, failed and uncertain reads are not verified coverage.' },
        selectionPriority: 'Explicit seed URLs reserve page slots first, then discovery slices select in input order, then followed links use any remaining slots. All share one page cap; slots are not balanced across slices.',
        incomplete: false, pages: [], jobs: [], records: [], errors: [], warnings: [], discovery: null, searchSlices: [],
      },
    };
    const report = parseReport(JSON.stringify(run), `lynk-run-${runId}.json`);
    expect(report.records).toHaveLength(0);
    expect(report.runSummary.input.boards).toEqual([board]);
    expect(report.runSummary.counts.successfulEmptyBoards).toBe(1);
    expect(report.runSummary.progress.total).toBe(run.units.length);
    expect(parseReport(JSON.stringify(exportReport(report)))).toEqual(report);
  });
  test('round-trips valid zero-result bundles including identity, diagnostics, omissions and empty CSV', () => {
    const report = buildReport(emptyColliderRun()), bundle = exportReport(report);
    expect(bundle.files['evidence.jsonl']).toBe('');
    expect(bundle.files['evidence.csv'].trim().split(/\r?\n/)).toHaveLength(1);
    expect(bundle.manifest.runSummary).toEqual(report.runSummary);
    expect(bundle.manifest.internetCoveragePercent).toBe(null);
    expect(parseReport(JSON.stringify(bundle), 'fynd-research-bundle.json')).toEqual(report);
    const another = emptyColliderRun(); another.id = '00000000-0000-4000-8000-000000000002';
    expect(buildReport(another).id).not.toBe(report.id);
  });
  test('rejects empty junk, incomplete run lookalikes and contradictory zero-evidence counts', () => {
    for (const input of [{}, [], { records: [] }, { result: { pages: [], jobs: [], records: [] } }, { manifest: { schemaVersion: 1 }, files: {} }]) {
      expect(() => parseReport(JSON.stringify(input))).toThrow();
    }
    for (const change of [input => { input.id = 'not-a-run-id'; }, input => { delete input.progress; }, input => { delete input.result.counts.savedPages; },
      input => { input.progress.done = 0; }, input => { input.input.query = ''; }, input => { input.result.counts.savedJobs = 1; }]) {
      const input = emptyColliderRun(); change(input);
      expect(() => buildReport(input)).toThrow();
    }
    const bundle = exportReport(buildReport(emptyColliderRun()));
    bundle.manifest.runSummary.status = 'invented';
    expect(() => parseReport(JSON.stringify(bundle))).toThrow(/Invalid Collider/);
  });
  test('bounds and validates run diagnostics without treating imported text as trusted data', () => {
    const input = emptyColliderRun();
    input.result.errors[0].url = 'http://127.0.0.1/private';
    expect(() => buildReport(input)).toThrow(/public http/);
    input.result.errors = Array.from({ length: 1001 }, () => ({ code: 'SOURCE_TIMEOUT' }));
    expect(() => buildReport(input)).toThrow(/run-summary limit/);
  });
  test('accepts portable bundles larger than the raw-report limit without raising the raw limit', () => {
    const report = buildReport(Array.from({ length: 40 }, (_, index) => row({ url: `https://example.com/large-${index}`, content: '\\'.repeat(50000), contentStatus: 'full' })));
    const bundleText = JSON.stringify(exportReport(report));
    expect(new Blob([bundleText]).size > 5 * 1024 * 1024).toBe(true);
    expect(new Blob([bundleText]).size < 20 * 1024 * 1024).toBe(true);
    expect(parseReport(bundleText).id).toBe(report.id);
    expect(() => parseReport(JSON.stringify({ records: [row({ content: 'x'.repeat(5 * 1024 * 1024) })] }))).toThrow(/5 MB/);
  });
  test('filters evidence by kind, completeness and search', () => {
    const report = buildReport([row({ kind: 'paper', content: 'retained science', contentStatus: 'full', source: 'Journal', doi: '10.1234/xyz' }), row({ kind: 'video' })]);
    expect(filterRecords(report, { kind: 'studies', contentStatus: 'full', query: 'science' })).toHaveLength(1);
    expect(filterRecords(report, { kind: 'code' })).toHaveLength(0);
    expect(filterRecords(report, { query: 'Journal' })).toHaveLength(1);
    expect(filterRecords(report, { query: '10.1234/xyz' })).toHaveLength(1);
  });
  test('dossier keeps subdomains and claims unverified; historical does not mean old', () => {
    const report = buildReport([
      row({ url: 'https://example.com/products/payments' }), row({ url: 'https://example.com/docs/start' }),
      row({ url: 'https://example.com/newsroom/new' }), row({ url: 'https://example.com/roadmap' }),
      row({ url: 'https://docs.example.com/api' }), row({ url: 'https://example-payments.com/news' }),
      row({ url: 'https://example.org/archive', historical: true }),
      row({ url: 'https://example.net/page', association: { domain: 'example.com', claim: 'affiliate' } }),
    ]);
    const dossier = buildDossier(report, 'example.com');
    ['products', 'docs', 'announcements', 'roadmap', 'independent', 'historical'].forEach(section => expect(dossier.sections[section]).toHaveLength(1));
    expect(dossier.sections.associatedUnverified).toHaveLength(2);
    expect(() => buildDossier(report, 'https://example.com/products')).toThrow(/hostname/);
    expect(() => buildDossier(report, 'unseen.example.com')).toThrow(/no evidence/);
    const unrelated = buildDossier(buildReport([row(), row({ url: 'https://unrelated.org', association: { domain: 'other.com', claim: 'affiliate' } })]), 'example.com');
    expect(unrelated.sections.associatedUnverified).toHaveLength(0);
  });
  test('exports retained trace and stable joins with honest omissions and CSV injection defense', () => {
    const report = buildReport({ records: [row({ title: '=HYPERLINK("bad")', emails: ['private@example.com'] })], candidates: [row({ selected: false, reason: 'limit reached' })], outcomes: [row({ status: 'failed', reason: 'timeout' })], edges: [{ from: 'https://example.com', to: 'https://example.com/paper' }] });
    const result = exportReport(report);
    expect(result.manifest.internetCoveragePercent).toBe(null);
    expect(result.files['evidence.csv']).toContain("'=HYPERLINK");
    expect(result.files['evidence.jsonl']).not.toContain('private@example.com');
    expect(JSON.parse(result.files['candidates.jsonl']).reason).toBe('limit reached');
    expect(JSON.parse(result.files['outcomes.jsonl']).evidenceIds).toEqual([report.records[0].id]);
    expect(JSON.parse(result.files['outcomes.jsonl']).evidenceLinkBasis).toMatch(/producing fetch attempt is unknown/);
    expect(JSON.parse(result.files['edges.jsonl']).targetUrlId).toBe(report.records[0].urlId);
    expect(result.files['urls.jsonl'].trim().split('\n')).toHaveLength(2);
    const roundTrip = parseReport(JSON.stringify(result), 'research-bundle.json');
    expect(roundTrip.records.map(record => record.id)).toEqual(report.records.map(record => record.id));
    expect(roundTrip.trace).toEqual(report.trace);
  });
  test('preserves source omissions, warnings and explicit truncation', () => {
    const report = buildReport({ records: [row()], omissions: ['Provider dropped 30 candidates.'], warnings: ['Stale source export.'], truncated: true });
    expect(report.omissions.join(' ')).toMatch(/30 candidates/);
    expect(report.omissions.join(' ')).toMatch(/truncation/);
    expect(report.warnings).toContain('Stale source export.');
    expect(parseReport(JSON.stringify(exportReport(report))).omissions).toContain('Provider dropped 30 candidates.');
  });
  test('preserves all imported notes up to 1000 and rejects overflow rather than truncating', () => {
    const warnings = Array.from({ length: 1000 }, (_, index) => `Warning ${index}`);
    const omissions = Array.from({ length: 1000 }, (_, index) => `Omission ${index}`);
    const report = buildReport({ records: [row()], warnings, omissions });
    expect(report.warnings).toEqual(warnings);
    expect(omissions.every(note => report.omissions.includes(note))).toBe(true);
    expect(() => buildReport({ records: [row()], warnings: [...warnings, 'Overflow'] })).toThrow(/1,000-note/);
    expect(() => buildReport({ records: [row()], omissions: [...omissions, 'Overflow'] })).toThrow(/1,000-note/);
    expect(() => buildReport({ records: [row()], warnings: ['x'.repeat(1001)] })).toThrow(/1,000 characters/);
    expect(() => buildReport({ records: [row()], omissions: [null] })).toThrow(/must be strings/);
  });
  test('portable note imports preserve entries beyond the old 100-note boundary', () => {
    const report = buildReport({ records: [row()], warnings: Array.from({ length: 150 }, (_, index) => `Retained warning ${index}`), omissions: Array.from({ length: 150 }, (_, index) => `Retained omission ${index}`) });
    expect(parseReport(JSON.stringify(exportReport(report)), 'saved-report.json')).toEqual(report);
  });
});
