import React from 'react';
import { act, fireEvent, render as rtlRender, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Research from './Research';
import { parseReport, exportReport } from '../lib/researchReport';
import { accountSnapshot, ACCOUNT_LIMITS } from '../lib/researchAccount';
import { api } from '../lib/api';

jest.mock('../lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
const scanCapabilities = { available: true, reason: null, limits: { max_pages_per_run: 20, max_snapshot_bytes: 8388608, max_snapshots: 500 }, scope: 'Configured scan transport only.' };
const render = (element, { scanAvailable = false } = {}) => {
  // Legacy manual-import cases deliberately keep the independent availability
  // request pending. Scan coordination cases opt into the real panel contract.
  api.get.mockImplementationOnce(url => {
    if (url !== '/api/v1/collider/scans/capabilities') throw new Error('Expected the bounded scan availability request first.');
    return scanAvailable ? Promise.resolve({ data: scanCapabilities }) : new Promise(() => {});
  });
  return rtlRender(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{element}</MemoryRouter>);
};

describe('Research stored-job connection', () => {
  const id = '1393c281-2d9f-4ed8-a38f-16b7c4b02f6d';
  const storedJob = { id, title: 'Stored research job', company_name: 'Example', origin_url: 'https://example.org/careers/research', jd_text: 'Stored description, not freshly collected.', is_sample: false };
  const startJob = () => {
    fireEvent.change(screen.getByLabelText('Fynd job ID or internal path'), { target: { value: id } });
    fireEvent.click(screen.getByRole('button', { name: 'Load Fynd job', exact: true }));
  };
  beforeEach(() => api.get.mockReset());

  test('opens an existing job as evidence, then clears back to the import screen', async () => {
    api.get.mockResolvedValue({ data: storedJob });
    render(<Research />);
    await act(async () => { startJob(); });
    expect(screen.getByRole('heading', { name: 'Example — Stored research job' })).toBeTruthy();
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(1);
    expect(screen.getByText('Stored description, not freshly collected.')).toBeTruthy();
    expect(screen.queryByTestId('fynd-job-research-import')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Clear report' }));
    expect(screen.getByTestId('fynd-job-research-import')).toBeTruthy();
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
  });

  test('a newer stored-job request invalidates an older file read immediately', async () => {
    let finishFile, finishJob;
    api.get.mockReturnValue(new Promise(resolve => { finishJob = resolve; }));
    render(<Research />);
    uploadFile({ name: 'old.json', size: 20, text: () => new Promise(resolve => { finishFile = resolve; }) });
    startJob();
    await act(async () => { finishFile(JSON.stringify(reportFixture)); });
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    await act(async () => { finishJob({ data: storedJob }); });
    expect(screen.getByRole('heading', { name: 'Example — Stored research job' })).toBeTruthy();
  });

  test('starting a file read aborts an older job request before the file completes', async () => {
    let finishFile, finishJob;
    api.get.mockReturnValue(new Promise(resolve => { finishJob = resolve; }));
    render(<Research />); startJob();
    const signal = api.get.mock.calls.find(([url]) => url === `/api/v1/jobs/${id}`)[1].signal;
    uploadFile({ name: 'new.json', size: 20, text: () => new Promise(resolve => { finishFile = resolve; }) });
    expect(signal.aborted).toBe(true);
    await act(async () => { finishJob({ data: storedJob }); });
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    await act(async () => { finishFile(JSON.stringify(reportFixture)); });
    expect(screen.getByRole('heading', { name: reportFixture.title })).toBeTruthy();
  });

  test('pasting a report cancels a pending job load and keeps the pasted evidence', async () => {
    let finishJob;
    api.get.mockReturnValue(new Promise(resolve => { finishJob = resolve; }));
    render(<Research />); startJob();
    const signal = api.get.mock.calls.find(([url]) => url === `/api/v1/jobs/${id}`)[1].signal;
    openPastedReport();
    expect(signal.aborted).toBe(true);
    await act(async () => { finishJob({ data: storedJob }); });
    expect(screen.getByRole('heading', { name: reportFixture.title })).toBeTruthy();
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(3);
  });
});

const reportFixture = {
  title: 'Fixture evidence — not live research',
  records: [
    {
      id: 'paper-html',
      url: 'https://example.org/study',
      title: 'Study HTML version',
      kind: 'paper',
      contentStatus: 'full',
      content: 'The complete body retained for this synthetic study fixture.',
      identifiers: { doi: ['10.1234/fixture-study'] },
    },
    {
      id: 'paper-pdf',
      url: 'https://example.org/study.pdf',
      title: 'Study PDF version',
      kind: 'paper',
      contentStatus: 'partial',
      content: 'Only an abstract was retained for this synthetic fixture.',
      identifiers: { doi: ['10.1234/fixture-study'] },
    },
    {
      id: 'news-item',
      url: 'https://example.net/news/study',
      title: 'Independent news fixture',
      kind: 'news',
      contentStatus: 'metadata',
    },
  ],
};

const companyFixture = {
  title: 'Synthetic company source boundaries',
  records: [
    { id: 'product', url: 'https://example.com/products/payments', title: 'Selected host product', kind: 'web' },
    { id: 'lookalike', url: 'https://example.com.other.org/products/payments', title: 'Lookalike host product', kind: 'web' },
    { id: 'suffix', url: 'https://notexample.com/products/payments', title: 'Unrelated suffix product', kind: 'web' },
    { id: 'subdomain', url: 'https://docs.example.com/products/payments', title: 'Unverified subdomain product', kind: 'web' },
  ],
};
const zeroResultFixture = {
  id: '00000000-0000-4000-8000-000000000003', status: 'failed',
  input: { urls: ['https://example.org/unavailable'], boards: [], pageLimit: 1, followLinks: false },
  progress: { total: 1, done: 1, pending: 0, inflight: 0, completed: 0, partial: 0, failed: 1, uncertain: 0 },
  units: [{ id: 'failed-page', kind: 'page', status: 'failed', input: { url: 'https://example.org/unavailable' }, error: 'SOURCE_TIMEOUT' }],
  result: { pages: [], jobs: [], records: [], incomplete: true,
    counts: { savedPages: 0, savedJobs: 0, structuredRecords: 0, successfulEmptyBoards: 0, selectedPages: 1, attemptedPages: 1, discoveredUrls: 1, notFetched: 1, frontierOmitted: 0, linksSkipped: 0, omittedRecords: 0, truncatedRecords: 0 },
    errors: [{ code: 'SOURCE_TIMEOUT', unitId: 'failed-page', url: 'https://example.org/unavailable' }], warnings: [], searchSlices: [] },
};

function openPastedReport(value = reportFixture) {
  // Opening details also exercises the entry point available to keyboard users.
  fireEvent.click(screen.getByText('Paste report JSON or get an example format'));
  fireEvent.change(screen.getByLabelText('Report JSON'), {
    target: { value: typeof value === 'string' ? value : JSON.stringify(value) },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Open pasted report' }));
}

function uploadFile(file) {
  fireEvent.change(screen.getByLabelText('Import evidence report'), {
    target: { files: [file] },
  });
}

describe('Research account, file and stored-job import coordination', () => {
  const accountEndpoint = '/api/v1/research/reports';
  const savedId = 'e2a269bb-3055-41d1-8704-3af29bce1f35';
  const jobId = '1393c281-2d9f-4ed8-a38f-16b7c4b02f6d';
  const jobEndpoint = `/api/v1/jobs/${jobId}`;
  const savedTitle = 'Saved account research fixture';
  const savedReport = parseReport(JSON.stringify({ ...reportFixture, title: savedTitle }));
  const bundle = accountSnapshot(savedReport);
  const metadata = { id: savedId, title: savedTitle, saved_at: '2026-09-13T09:00:00Z', byte_size: new Blob([JSON.stringify(bundle)]).size };
  const detail = { report: { ...metadata, bundle } };
  const savedEndpoint = `${accountEndpoint}/${savedId}`;
  const storedJob = { id: jobId, title: 'Account-race job fixture', company_name: 'Example', origin_url: 'https://example.org/careers/research', jd_text: 'Stored job body, not live collection.', is_sample: false };
  const jobTitle = 'Example — Account-race job fixture';

  function pending() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
  }
  async function prepareSavedList() {
    api.get.mockResolvedValueOnce({ data: { reports: [metadata], used_bytes: metadata.byte_size, limits: ACCOUNT_LIMITS } });
    fireEvent.click(screen.getByRole('button', { name: 'Saved reports', exact: true }));
    await screen.findByRole('heading', { name: savedTitle, level: 3 });
  }
  function openSaved() { fireEvent.click(screen.getByRole('button', { name: `Open saved report: ${savedTitle}` })); }
  function startJob() {
    fireEvent.change(screen.getByLabelText('Fynd job ID or internal path'), { target: { value: jobId } });
    fireEvent.click(screen.getByRole('button', { name: 'Load Fynd job', exact: true }));
  }
  function requestSignal(url) { return api.get.mock.calls.find(([target]) => target === url)[1].signal; }
  beforeEach(() => { api.get.mockReset(); api.post.mockReset(); api.delete.mockReset(); });

  test('starting an account load immediately invalidates an older pending file read', async () => {
    render(<Research />);
    await prepareSavedList();
    const file = pending(), account = pending();
    uploadFile({ name: 'older-file.json', size: 200, text: () => file.promise });
    api.get.mockReturnValueOnce(account.promise);
    openSaved();

    await act(async () => { file.resolve(JSON.stringify(reportFixture)); });
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    expect(screen.queryByRole('heading', { name: reportFixture.title, level: 2 })).toBeNull();
    expect(screen.getByRole('button', { name: 'Import report', exact: true }).disabled).toBe(false);
    await act(async () => { account.resolve({ data: detail }); });

    expect(screen.getByRole('heading', { name: savedTitle, level: 2 })).toBeTruthy();
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(3);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  test('starting a file read aborts an older account load before the file finishes', async () => {
    render(<Research />);
    await prepareSavedList();
    const account = pending(), file = pending();
    api.get.mockReturnValueOnce(account.promise);
    openSaved();
    const signal = requestSignal(savedEndpoint);
    uploadFile({ name: 'newer-file.json', size: 200, text: () => file.promise });
    expect(signal.aborted).toBe(true);

    await act(async () => { account.resolve({ data: detail }); });
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    expect(screen.queryByRole('heading', { name: savedTitle, level: 2 })).toBeNull();
    await act(async () => { file.resolve(JSON.stringify(reportFixture)); });

    expect(screen.getByRole('heading', { name: reportFixture.title, level: 2 })).toBeTruthy();
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(3);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  test('starting an account load aborts an older stored-job request', async () => {
    render(<Research />);
    await prepareSavedList();
    const job = pending(), account = pending();
    api.get.mockReturnValueOnce(job.promise);
    startJob();
    const signal = requestSignal(jobEndpoint);
    api.get.mockReturnValueOnce(account.promise);
    openSaved();
    expect(signal.aborted).toBe(true);

    await act(async () => { job.resolve({ data: storedJob }); });
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    expect(screen.queryByRole('heading', { name: jobTitle, level: 2 })).toBeNull();
    await act(async () => { account.resolve({ data: detail }); });

    expect(screen.getByRole('heading', { name: savedTitle, level: 2 })).toBeTruthy();
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(3);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('starting a stored-job request aborts an older account load', async () => {
    render(<Research />);
    await prepareSavedList();
    const account = pending(), job = pending();
    api.get.mockReturnValueOnce(account.promise);
    openSaved();
    const signal = requestSignal(savedEndpoint);
    api.get.mockReturnValueOnce(job.promise);
    startJob();
    expect(signal.aborted).toBe(true);

    await act(async () => { account.resolve({ data: detail }); });
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    expect(screen.queryByRole('heading', { name: savedTitle, level: 2 })).toBeNull();
    await act(async () => { job.resolve({ data: storedJob }); });

    expect(screen.getByRole('heading', { name: jobTitle, level: 2 })).toBeTruthy();
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(1);
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('Research workspace', () => {
  test('makes its imported-only and unsaved state explicit before any data is loaded', () => {
    render(<Research />);

    expect(screen.getByTestId('research-empty')).toBeTruthy();
    const scope = screen.getByRole('note', { name: 'Research evidence scope' }).textContent;
    expect(scope).toContain('Scan availability depends on the configured service and permitted sources');
    expect(scope).toContain('unless you explicitly save to your account');
    expect(scope).toContain('Clearing this tab does not delete saved account copies');
    expect(scope).toContain('Starting a scan explicitly stores source content');
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Download bundle' })).toBeNull();
    expect(screen.getByLabelText('Report JSON').maxLength).toBe(20 * 1024 * 1024);
  });

  test('shows a valid zero-result Collider run instead of an import failure and retains diagnostics', () => {
    render(<Research />);
    openPastedReport(zeroResultFixture);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByTestId('research-empty')).toBeNull();
    expect(screen.getByRole('heading', { name: 'Imported Collider run' })).toBeTruthy();
    expect(screen.getByText('Run status: failed · 1 of 1 recorded steps settled')).toBeTruthy();
    expect(screen.getByText(/This imported run contains no collected evidence/)).toBeTruthy();
    expect(screen.getByText(/Empty results do not prove absence/)).toBeTruthy();
    expect(screen.queryByText(/No records match these filters/)).toBeNull();
    expect(screen.getByText(/SOURCE_TIMEOUT/)).toBeTruthy();
    expect(screen.getAllByRole('status').some(item => item.textContent === '0 matching records')).toBe(true);
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Discovery trail' }));
    expect(screen.getByText('Retained fetch outcomes').parentElement.textContent).toContain('1');
    expect(screen.getByRole('button', { name: 'Download traceable bundle' })).toBeTruthy();
  });

  test('accepts a zero-result replacement file but retains it when subsequent empty junk is imported', async () => {
    render(<Research />);
    openPastedReport();
    await act(async () => { uploadFile({ name: 'zero-result.json', size: 1000, text: jest.fn().mockResolvedValue(JSON.stringify(zeroResultFixture)) }); });
    expect(screen.getByRole('heading', { name: 'Imported Collider run' })).toBeTruthy();
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    await act(async () => { uploadFile({ name: 'empty-junk.json', size: 2, text: jest.fn().mockResolvedValue('{}') }); });
    expect(screen.getByRole('alert').textContent).toContain('Your previously loaded report is unchanged.');
    expect(screen.getByRole('heading', { name: 'Imported Collider run' })).toBeTruthy();
  });

  test('opens pasted JSON without representing metadata as retained full content', () => {
    render(<Research />);
    openPastedReport();

    expect(screen.getByRole('heading', { name: reportFixture.title })).toBeTruthy();
    expect(screen.queryByTestId('research-empty')).toBeNull();
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(3);
    const news = screen.getByRole('heading', { name: 'Independent news fixture' }).closest('article');
    expect(within(news).getByText('metadata only')).toBeTruthy();
    expect(within(news).queryByText('Read retained content')).toBeNull();
    const source = within(news).getByRole('link', { name: 'Open source' });
    expect(source.getAttribute('rel')).toBe('noopener noreferrer');
    expect(source.getAttribute('referrerpolicy')).toBe('no-referrer');
  });

  test('combines evidence kind, retained content state, and report search filters', () => {
    render(<Research />);
    openPastedReport();

    fireEvent.change(screen.getByLabelText('Evidence kind'), { target: { value: 'studies' } });
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(2);
    fireEvent.change(screen.getByLabelText('Content obtained'), { target: { value: 'partial' } });
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(1);
    expect(screen.getByRole('heading', { name: 'Study PDF version' })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Study HTML version' })).toBeNull();

    fireEvent.change(screen.getByLabelText('Search this report'), { target: { value: 'no-such-record' } });
    expect(screen.getByRole('status').textContent).toBe('0 matching records');
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    expect(screen.getByText(/No records match these filters/)).toBeTruthy();
  });

  test('rejects invalid pasted content without creating a report', () => {
    render(<Research />);
    openPastedReport('{ this is not JSON }');

    expect(screen.getByRole('alert').textContent.length).toBeGreaterThan(0);
    expect(screen.getByTestId('research-empty')).toBeTruthy();
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
  });

  test('preserves the previous report when a replacement file cannot be parsed', async () => {
    render(<Research />);
    openPastedReport();
    uploadFile({ name: 'broken.json', size: 12, text: jest.fn().mockResolvedValue('{ broken }') });

    await screen.findByRole('alert');
    expect(screen.getByRole('alert').textContent).toContain('Your previously loaded report is unchanged.');
    expect(screen.getByRole('heading', { name: reportFixture.title })).toBeTruthy();
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(3);
  });

  test('shows shared DOI relationships while keeping distinct evidence records', () => {
    render(<Research />);
    openPastedReport();
    expect(screen.getByText('3 retained evidence records · 1 identifier relationship')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Research links' }));

    expect(screen.getByRole('heading', { name: 'Related, not interchangeable.' })).toBeTruthy();
    expect(screen.getByText(/10\.1234\/fixture-study/)).toBeTruthy();
    expect(screen.getByText(/A shared identifier is not independent corroboration/)).toBeTruthy();
    const relationshipList = screen.getAllByRole('list').find(list => list.textContent.includes('10.1234/fixture-study'));
    expect(relationshipList).toBeTruthy();
    expect(relationshipList.textContent).toContain('Study HTML version');
    expect(relationshipList.textContent).toContain('Study PDF version');

    fireEvent.click(screen.getByRole('button', { name: 'Evidence', exact: true }));
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(3);
  });

  test('does not promote lookalike domains or unverified subdomains to official products', () => {
    render(<Research />);
    openPastedReport(companyFixture);
    fireEvent.click(screen.getByRole('button', { name: 'Company dossier' }));
    fireEvent.change(screen.getByLabelText('Company hostname'), { target: { value: 'example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Organize dossier' }));

    expect(screen.getByText(/Selected host: example.com/)).toBeTruthy();
    const products = screen.getByRole('heading', { name: 'Products', exact: true }).closest('section');
    expect(within(products).getByRole('link', { name: 'Selected host product' })).toBeTruthy();
    for (const title of ['Lookalike host product', 'Unrelated suffix product', 'Unverified subdomain product']) {
      expect(within(products).queryByRole('link', { name: title })).toBeNull();
      expect(screen.getByRole('link', { name: title })).toBeTruthy();
    }
  });

  test('clears imported records and returns to the empty state', () => {
    render(<Research />);
    openPastedReport();
    fireEvent.click(screen.getByRole('button', { name: 'Clear report' }));

    expect(screen.getByTestId('research-empty')).toBeTruthy();
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    expect(screen.queryByRole('heading', { name: reportFixture.title })).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('rejects files over the portable-bundle limit before reading their contents', async () => {
    render(<Research />);
    const read = jest.fn();
    uploadFile({ name: 'oversized.json', size: 20 * 1024 * 1024 + 1, text: read });

    expect((await screen.findByRole('alert')).textContent).toContain('Choose a file smaller than 20 MB.');
    expect(read).not.toHaveBeenCalled();
    expect(screen.getByTestId('research-empty')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Import report' }).disabled).toBe(false);
  });

  test('a slow file read cannot replace a newer pasted report', async () => {
    render(<Research />);
    let finishRead;
    uploadFile({ name: 'slow.json', size: 200, text: () => new Promise(resolve => { finishRead = resolve; }) });
    expect(screen.getByRole('button', { name: 'Reading…' }).disabled).toBe(true);

    openPastedReport();
    await act(async () => {
      finishRead(JSON.stringify({ title: 'Stale slow file', records: [{ url: 'https://example.org/stale', title: 'Stale evidence' }] }));
    });
    expect(screen.getByRole('heading', { name: reportFixture.title })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Stale slow file' })).toBeNull();
    expect(screen.getAllByTestId('evidence-record')).toHaveLength(3);
    expect(screen.getByRole('button', { name: 'Import report' }).disabled).toBe(false);
  });

  test('clearing a report also invalidates any pending replacement import', async () => {
    render(<Research />);
    openPastedReport();
    let finishRead;
    uploadFile({ name: 'pending.json', size: 200, text: () => new Promise(resolve => { finishRead = resolve; }) });
    fireEvent.click(screen.getByRole('button', { name: 'Clear report' }));
    await act(async () => { finishRead(JSON.stringify(reportFixture)); });

    expect(screen.getByTestId('research-empty')).toBeTruthy();
    expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Import report' }).disabled).toBe(false);
  });

  test('creates a downloadable bundle and evidence CSV and releases their object URLs', () => {
    const oldCreate = URL.createObjectURL;
    const oldRevoke = URL.revokeObjectURL;
    URL.createObjectURL = jest.fn().mockReturnValue('blob:research-fixture');
    URL.revokeObjectURL = jest.fn();
    const clicked = [];
    const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      clicked.push({ name: this.download, href: this.getAttribute('href') });
    });
    jest.useFakeTimers();
    try {
      render(<Research />);
      openPastedReport();
      fireEvent.click(screen.getByRole('button', { name: 'Download bundle' }));
      fireEvent.click(screen.getByRole('button', { name: 'Export all evidence CSV' }));

      expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
      expect(URL.createObjectURL.mock.calls[0][0]).toBeInstanceOf(Blob);
      expect(URL.createObjectURL.mock.calls[0][0].type).toBe('application/json');
      expect(URL.createObjectURL.mock.calls[1][0].type).toBe('text/csv;charset=utf-8');
      expect(clicked).toEqual([
        { name: 'fynd-research-bundle.json', href: 'blob:research-fixture' },
        { name: 'fynd-evidence.csv', href: 'blob:research-fixture' },
      ]);
      expect(document.querySelector('a[download]')).toBeNull();
      act(() => jest.runOnlyPendingTimers());
      expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:research-fixture');
      expect(screen.queryByRole('alert')).toBeNull();
    } finally {
      jest.useRealTimers();
      click.mockRestore();
      URL.createObjectURL = oldCreate;
      URL.revokeObjectURL = oldRevoke;
    }
  });

  test('shows retained trace counts and explicit missing-history information', () => {
    render(<Research />);
    openPastedReport();
    fireEvent.click(screen.getByRole('button', { name: 'Discovery trail' }));

    expect(screen.getByRole('heading', { name: 'A portable, inspectable trail.' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Missing or omitted information' })).toBeTruthy();
    expect(screen.getByText('Retained candidates')).toBeTruthy();
    expect(screen.getByText('Retained fetch outcomes')).toBeTruthy();
    expect(screen.getByText('Retained discovery edges')).toBeTruthy();
    expect(screen.getByText(/not every upstream search result or a complete archive/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Download traceable bundle' })).toBeTruthy();
  });

  describe('readable export fallback', () => {
    let oldCreate, oldRevoke, oldClipboard, blobSpy, writeText;
    beforeEach(() => {
      oldCreate = URL.createObjectURL;
      oldRevoke = URL.revokeObjectURL;
      oldClipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
      URL.createObjectURL = jest.fn().mockReturnValue('blob:research-export');
      URL.revokeObjectURL = jest.fn();
      const OriginalBlob = window.Blob;
      blobSpy = jest.spyOn(window, 'Blob').mockImplementation((parts, options) => new OriginalBlob(parts, options));
      jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
      writeText = jest.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
      jest.useFakeTimers();
    });
    afterEach(() => {
      act(() => jest.runOnlyPendingTimers());
      jest.useRealTimers();
      jest.restoreAllMocks();
      URL.createObjectURL = oldCreate;
      URL.revokeObjectURL = oldRevoke;
      if (oldClipboard) Object.defineProperty(navigator, 'clipboard', oldClipboard);
      else delete navigator.clipboard;
    });

    test('shows JSON and CSV text identical to the attempted download bodies without copying automatically', () => {
      render(<Research />);
      openPastedReport();
      const expected = exportReport(parseReport(JSON.stringify(reportFixture)));
      fireEvent.click(screen.getByRole('button', { name: 'Download bundle' }));
      const jsonText = screen.getByLabelText('Export text');
      expect(jsonText.readOnly).toBe(true);
      expect(jsonText.value).toBe(JSON.stringify(expected, null, 2));
      expect(JSON.parse(jsonText.value)).toEqual(expected);
      expect(blobSpy.mock.calls.find(([, options]) => options?.type === 'application/json')[0]).toEqual([jsonText.value]);
      expect(screen.getByText('Filename: fynd-research-bundle.json')).toBeTruthy();
      expect(screen.getByText(/cannot confirm whether your browser saved the file/)).toBeTruthy();
      expect(screen.getByText(/Downloaded files and clipboard copies are not removed/)).toBeTruthy();
      expect(writeText).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole('button', { name: 'Export all evidence CSV' }));
      const csvText = screen.getByLabelText('Export text').value;
      // Textarea values normalize line endings; download and clipboard preserve the original CSV bytes.
      expect(csvText).toBe(expected.files['evidence.csv'].replace(/\r\n/g, '\n'));
      expect(blobSpy.mock.calls.find(([, options]) => options?.type === 'text/csv;charset=utf-8')[0]).toEqual([expected.files['evidence.csv']]);
      expect(screen.getByText('Filename: fynd-evidence.csv')).toBeTruthy();
      expect(screen.queryByText('Filename: fynd-research-bundle.json')).toBeNull();
      expect(writeText).not.toHaveBeenCalled();
    });

    test('exports and reopens a zero-result run without losing its summary or diagnostics', () => {
      render(<Research />);
      openPastedReport(zeroResultFixture);
      fireEvent.click(screen.getByRole('button', { name: 'Download bundle' }));
      const bundleText = screen.getByLabelText('Export text').value;
      expect(JSON.parse(bundleText).manifest.runSummary.errors[0].code).toBe('SOURCE_TIMEOUT');
      fireEvent.click(screen.getByRole('button', { name: 'Clear report' }));
      openPastedReport(bundleText);
      expect(screen.queryByRole('alert')).toBeNull();
      expect(screen.getByRole('heading', { name: 'Imported Collider run' })).toBeTruthy();
      expect(screen.getByText(/SOURCE_TIMEOUT/)).toBeTruthy();
      expect(screen.queryAllByTestId('evidence-record')).toHaveLength(0);
    });

    test.each([false, true])('copies the prepared export bytes only after an explicit click (CSV: %s)', async csv => {
      render(<Research />);
      openPastedReport();
      const expected = exportReport(parseReport(JSON.stringify(reportFixture)));
      fireEvent.click(screen.getByRole('button', { name: csv ? 'Export all evidence CSV' : 'Download bundle' }));
      const text = csv ? expected.files['evidence.csv'] : JSON.stringify(expected, null, 2);
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Copy export' })); });
      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith(text);
      expect(screen.getByText(/Export copied\. Paste it into a text file/)).toBeTruthy();
      expect(screen.getByRole('button', { name: 'Copy export' }).disabled).toBe(false);
    });

    test.each(['denied', 'unavailable'])('keeps selectable export text and manual instructions when the clipboard is %s', async mode => {
      if (mode === 'denied') writeText.mockRejectedValue(new Error('Permission denied'));
      else Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
      render(<Research />);
      openPastedReport();
      fireEvent.click(screen.getByRole('button', { name: 'Download bundle' }));
      const text = screen.getByLabelText('Export text').value;
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Copy export' })); });
      expect(screen.getByText(/Select all text in the Export text box, copy it manually/)).toBeTruthy();
      expect(screen.getByLabelText('Export text').value).toBe(text);
      expect(screen.getAllByTestId('evidence-record')).toHaveLength(3);
      expect(screen.queryByRole('alert')).toBeNull();
    });

    test('retains the valid report and fallback when starting the native download throws', () => {
      URL.createObjectURL.mockImplementation(() => { throw new Error('Download unavailable'); });
      render(<Research />);
      openPastedReport();
      fireEvent.click(screen.getByRole('button', { name: 'Download bundle' }));
      expect(screen.getByText(/The download could not be started/)).toBeTruthy();
      expect(JSON.parse(screen.getByLabelText('Export text').value).manifest.title).toBe(reportFixture.title);
      expect(screen.getByRole('heading', { name: reportFixture.title })).toBeTruthy();
      expect(screen.getAllByTestId('evidence-record')).toHaveLength(3);
      expect(screen.queryByRole('alert')).toBeNull();
    });

    test('clears export text and copy feedback when clearing and pasting a new report', async () => {
      render(<Research />);
      openPastedReport();
      fireEvent.click(screen.getByRole('button', { name: 'Download bundle' }));
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Copy export' })); });
      fireEvent.click(screen.getByRole('button', { name: 'Clear report' }));
      expect(screen.queryByLabelText('Export text')).toBeNull();
      expect(screen.queryByText(/Export copied/)).toBeNull();
      openPastedReport(companyFixture);
      expect(screen.queryByLabelText('Export text')).toBeNull();
      expect(screen.getByRole('heading', { name: companyFixture.title })).toBeTruthy();
    });

    test('keeps fallback for a rejected replacement and resets it only after a valid file finishes importing', async () => {
      render(<Research />);
      openPastedReport();
      fireEvent.click(screen.getByRole('button', { name: 'Download bundle' }));
      const text = screen.getByLabelText('Export text').value;
      await act(async () => { uploadFile({ name: 'broken.json', size: 12, text: jest.fn().mockResolvedValue('{ broken }') }); });
      expect(screen.getByRole('alert').textContent).toContain('Your previously loaded report is unchanged.');
      expect(screen.getByLabelText('Export text').value).toBe(text);
      let finishRead;
      uploadFile({ name: 'replacement.json', size: 200, text: () => new Promise(resolve => { finishRead = resolve; }) });
      expect(screen.getByLabelText('Export text').value).toBe(text);
      await act(async () => { finishRead(JSON.stringify(companyFixture)); });
      expect(screen.getByRole('heading', { name: companyFixture.title })).toBeTruthy();
      expect(screen.queryByLabelText('Export text')).toBeNull();
      expect(screen.queryByRole('alert')).toBeNull();
      expect(screen.getByRole('button', { name: 'Import report' }).disabled).toBe(false);
    });

    test('ignores stale clipboard completion after a different export or report clear', async () => {
      let finishCopy;
      writeText.mockImplementation(() => new Promise(resolve => { finishCopy = resolve; }));
      render(<Research />);
      openPastedReport();
      fireEvent.click(screen.getByRole('button', { name: 'Download bundle' }));
      fireEvent.click(screen.getByRole('button', { name: 'Copy export' }));
      expect(screen.getByRole('button', { name: 'Copy export' }).disabled).toBe(true);
      fireEvent.click(screen.getByRole('button', { name: 'Export all evidence CSV' }));
      await act(async () => { finishCopy(); });
      expect(screen.getByText('Filename: fynd-evidence.csv')).toBeTruthy();
      expect(screen.queryByText(/Export copied/)).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: 'Copy export' }));
      fireEvent.click(screen.getByRole('button', { name: 'Clear report' }));
      await act(async () => { finishCopy(); });
      expect(screen.queryByLabelText('Export text')).toBeNull();
      expect(screen.queryByText(/Export copied/)).toBeNull();
      expect(screen.getByTestId('research-empty')).toBeTruthy();
    });
  });
});
