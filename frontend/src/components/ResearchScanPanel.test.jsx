import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { api } from '../lib/api';
import { newScanRequestKey } from '../lib/researchScans';
import { parseReport } from '../lib/researchReport';
import { accountSnapshot } from '../lib/researchAccount';
import ResearchScanPanel from './ResearchScanPanel';

jest.mock('../lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('../lib/researchScans', () => ({ ...jest.requireActual('../lib/researchScans'), newScanRequestKey: jest.fn() }));
const endpoint = '/api/v1/collider/scans';
const id = 'a6623e49-2aa3-4311-8acf-127b32289b11', secondId = 'b6623e49-2aa3-4311-8acf-127b32289b22';
const caps = { available: true, reason: null, limits: { max_pages_per_run: 20, max_snapshot_bytes: 8388608, max_snapshots: 500 }, scope: 'Configured transport only.' };
function run(status = 'queued', runId = id) {
  const progress = { total: 1, done: 0, pending: 0, inflight: 0, completed: 0, partial: 0, failed: 0, uncertain: 0 };
  if (['completed', 'partial', 'failed'].includes(status)) { progress.done = 1; progress[status] = 1; }
  else if (['running', 'cancel_requested'].includes(status)) progress.inflight = 1;
  else progress.pending = 1;
  return { id: runId, status, input: { urls: ['https://example.org/evidence'], boards: [], pageLimit: 5, followLinks: false }, progress,
    createdAt: '2026-09-14T09:00:00Z', updatedAt: '2026-09-14T09:00:00Z',
    result: { incomplete: status !== 'completed', counts: { savedPages: ['completed', 'partial'].includes(status) ? 1 : 0, savedJobs: 0, structuredRecords: 0, successfulEmptyBoards: 0, selectedPages: 1, attemptedPages: 1, discoveredUrls: 1, notFetched: 0, frontierOmitted: 0, linksSkipped: 0, omittedRecords: 0, truncatedRecords: 0 } } };
}
function reportBundle(status = 'completed') {
  const value = run(status);
  value.result = { ...value.result, pages: ['completed', 'partial'].includes(status) ? [{ url: 'https://example.org/evidence', title: 'Collected fixture', content: 'Synthetic collected source body.' }] : [], jobs: [], records: [], errors: status === 'failed' ? [{ code: 'SOURCE_TIMEOUT' }] : [], warnings: [], searchSlices: [] };
  return accountSnapshot(parseReport(JSON.stringify(value)));
}
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
async function mount(props = {}) {
  const view = render(<ResearchScanPanel {...props} />);
  await act(async () => {});
  return view;
}
function consent() { fireEvent.click(screen.getByRole('checkbox', { name: 'I understand source content from this scan will be stored in my Fynd account' })); }
async function startScan(status = 'queued') {
  api.post.mockResolvedValueOnce({ data: { replay: false, run: run(status) } });
  fireEvent.change(screen.getByLabelText('Search query'), { target: { value: 'focused research' } });
  consent();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Start scan', exact: true })); });
}

describe('Research scan panel', () => {
  beforeEach(() => {
    api.get.mockReset(); api.post.mockReset(); newScanRequestKey.mockReset();
    api.get.mockImplementation(url => url === `${endpoint}/capabilities` ? Promise.resolve({ data: caps }) : Promise.reject(new Error('Unexpected test request')));
    newScanRequestKey.mockReturnValue('request-key-1');
  });

  test('checks configuration only on mount and never auto-starts or invents evidence', async () => {
    await mount();
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith(`${endpoint}/capabilities`, expect.objectContaining({ timeout: 15000, signal: expect.anything() }));
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.getByText(/does not establish that the engine or any source is healthy/)).toBeTruthy();
    expect(screen.queryByTestId('selected-scan')).toBeNull();
    expect(screen.getByRole('button', { name: 'Start scan', exact: true }).disabled).toBe(true);
  });

  test.each(['disabled', 'configuration_required'])('disables starting when availability is %s', async reason => {
    api.get.mockResolvedValue({ data: { ...caps, available: false, reason } });
    await mount();
    fireEvent.change(screen.getByLabelText('Search query'), { target: { value: 'query' } });
    consent();
    expect(screen.getByRole('button', { name: 'Start scan', exact: true }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Refresh saved scans' }).disabled).toBe(true);
    expect(api.post).not.toHaveBeenCalled();
  });

  test('requires explicit storage consent and validates input before starting', async () => {
    await mount();
    fireEvent.change(screen.getByLabelText('Search query'), { target: { value: 'query' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start scan', exact: true }));
    expect(api.post).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Search query'), { target: { value: '' } });
    consent();
    fireEvent.click(screen.getByRole('button', { name: 'Start scan', exact: true }));
    expect(screen.getByRole('alert').textContent).toContain('query or at least one');
    expect(api.post).not.toHaveBeenCalled();
  });

  test('sends bounded inputs with an idempotency key and does not call report-import hooks', async () => {
    const onBusy = jest.fn(), onImportReport = jest.fn();
    await mount({ onBusy, onImportReport });
    await startScan();
    expect(api.post).toHaveBeenCalledWith(endpoint, { input: { urls: [], query: 'focused research', pageLimit: 5, followLinks: false }, confirm_storage: true }, expect.objectContaining({ timeout: 20000, headers: { 'Idempotency-Key': 'request-key-1' }, signal: expect.anything() }));
    expect(screen.getByRole('heading', { name: 'Scan status: queued' })).toBeTruthy();
    expect(screen.getByText('0 of 1 recorded steps settled')).toBeTruthy();
    expect(screen.getByText(/not internet coverage/)).toBeTruthy();
    expect(onBusy).not.toHaveBeenCalled();
    expect(onImportReport).not.toHaveBeenCalled();
  });

  test('retains the same key after an uncertain start, even across a parent reset', async () => {
    const view = await mount({ resetKey: 0 });
    api.post.mockRejectedValueOnce({ code: 'ECONNABORTED' });
    fireEvent.change(screen.getByLabelText('Search query'), { target: { value: 'research' } });
    consent();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Start scan', exact: true })); });
    expect(screen.getByLabelText('Search query').disabled).toBe(true);
    expect(screen.getByText(/Retried|Retrying keeps the same request key/)).toBeTruthy();
    view.rerender(<ResearchScanPanel resetKey={1} />);
    api.post.mockResolvedValueOnce({ data: { replay: true, run: run() } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Retry same scan request' })); });

    expect(newScanRequestKey).toHaveBeenCalledTimes(1);
    expect(api.post.mock.calls[0][2].headers).toEqual(api.post.mock.calls[1][2].headers);
    expect(api.post.mock.calls[0][1]).toEqual(api.post.mock.calls[1][1]);
    expect(screen.getByText(/existing scan request was recovered/)).toBeTruthy();
  });

  test('requires an explicit choice before replacing uncertain inputs or minting a new key', async () => {
    await mount();
    api.post.mockRejectedValueOnce(new Error('Request timeout'));
    fireEvent.change(screen.getByLabelText('Search query'), { target: { value: 'original' } }); consent();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Start scan', exact: true })); });
    fireEvent.click(screen.getByRole('button', { name: 'Use different inputs' }));
    expect(screen.getByLabelText('Search query').disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Continue with different inputs' }));
    expect(screen.getByLabelText('Search query').disabled).toBe(false);
    newScanRequestKey.mockReturnValueOnce('request-key-2');
    api.post.mockResolvedValueOnce({ data: { replay: false, run: run() } });
    fireEvent.change(screen.getByLabelText('Search query'), { target: { value: 'changed research' } }); consent();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Start scan', exact: true })); });
    expect(api.post.mock.calls[1][2].headers['Idempotency-Key']).toBe('request-key-2');
  });

  test('polls no faster than five seconds and stops on a terminal state', async () => {
    jest.useFakeTimers();
    let view;
    try {
      view = await mount(); await startScan();
      api.get.mockResolvedValue({ data: { run: run('completed') } });
      await act(async () => { jest.advanceTimersByTime(4999); });
      expect(api.get.mock.calls.filter(([url]) => url === `${endpoint}/${id}`)).toHaveLength(0);
      await act(async () => { jest.advanceTimersByTime(1); });
      expect(screen.getByRole('heading', { name: 'Scan status: completed' })).toBeTruthy();
      await act(async () => { jest.advanceTimersByTime(60000); });
      expect(api.get.mock.calls.filter(([url]) => url === `${endpoint}/${id}`)).toHaveLength(1);
    } finally { view?.unmount(); jest.useRealTimers(); }
  });

  test('stops automatic status checks after sixty polls', async () => {
    jest.useFakeTimers();
    let view;
    try {
      view = await mount(); await startScan();
      api.get.mockResolvedValue({ data: { run: run() } });
      for (let index = 0; index < 60; index++) await act(async () => { jest.advanceTimersByTime(5000); });
      expect(api.get.mock.calls.filter(([url]) => url === `${endpoint}/${id}`)).toHaveLength(60);
      expect(screen.getByText(/Automatic status checks are paused/)).toBeTruthy();
      await act(async () => { jest.advanceTimersByTime(60000); });
      expect(api.get.mock.calls.filter(([url]) => url === `${endpoint}/${id}`)).toHaveLength(60);
    } finally { view?.unmount(); jest.useRealTimers(); }
  });

  test('cancel and resume are explicit and use the actual supported lifecycle', async () => {
    await mount(); await startScan('running');
    expect(api.post).toHaveBeenCalledTimes(1);
    api.post.mockResolvedValueOnce({ data: { run: run('cancel_requested') } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Cancel scan', exact: true })); });
    expect(api.post).toHaveBeenLastCalledWith(`${endpoint}/${id}/cancel`, {}, expect.objectContaining({ timeout: 15000 }));
    expect(screen.getByRole('heading', { name: 'Scan status: cancel requested' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Resume scan' })).toBeNull();

    api.get.mockResolvedValueOnce({ data: { run: run('paused') } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh scan status' })); });
    api.post.mockResolvedValueOnce({ data: { run: run() } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Resume scan' })); });
    expect(api.post).toHaveBeenLastCalledWith(`${endpoint}/${id}/resume`, {}, expect.objectContaining({ timeout: 15000 }));
    expect(screen.getByText(/Failed or uncertain reads are not automatically retried/)).toBeTruthy();
  });

  test('imports a completed report through the real parser only after an explicit click', async () => {
    const onImportReport = jest.fn(), onBusy = jest.fn();
    await mount({ onImportReport, onBusy }); await startScan('completed');
    expect(onImportReport).not.toHaveBeenCalled();
    api.get.mockResolvedValueOnce({ data: reportBundle() });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Open retained report' })); });
    expect(api.get).toHaveBeenLastCalledWith(`${endpoint}/${id}/report`, expect.objectContaining({ timeout: 35000, signal: expect.anything() }));
    expect(onImportReport).toHaveBeenCalledTimes(1);
    expect(onImportReport.mock.calls[0][0].records[0].content).toBe('Synthetic collected source body.');
    expect(onImportReport.mock.calls[0][0].runSummary.id).toBe(id);
    expect(onBusy.mock.calls).toEqual([[true], [false]]);
  });

  test('rejects a report for a different scan without changing the research workspace', async () => {
    const onImportReport = jest.fn();
    await mount({ onImportReport }); await startScan('completed');
    const bundle = reportBundle(); bundle.manifest.runSummary.id = secondId;
    api.get.mockResolvedValueOnce({ data: bundle });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Open retained report' })); });
    expect(onImportReport).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toBeTruthy();
  });

  test.each(['partial', 'failed', 'cancelled'])('opens retained evidence or diagnostics for %s without claiming collection success', async status => {
    const onImportReport = jest.fn();
    await mount({ onImportReport }); await startScan(status);
    api.get.mockResolvedValueOnce({ data: reportBundle(status) });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Open retained report' })); });
    expect(onImportReport.mock.calls[0][0].runSummary.status).toBe(status);
    expect(screen.getByRole('heading', { name: `Scan status: ${status}` })).toBeTruthy();
    expect(screen.queryByText(/Scan completed successfully/)).toBeNull();
  });

  test('parent reset aborts only a pending report import and preserves the server run', async () => {
    const onImportReport = jest.fn(), onBusy = jest.fn(), pending = deferred();
    const view = await mount({ onImportReport, onBusy, resetKey: 0 }); await startScan('completed');
    api.get.mockReturnValueOnce(pending.promise);
    fireEvent.click(screen.getByRole('button', { name: 'Open retained report' }));
    const signal = api.get.mock.calls.find(([url]) => url.endsWith('/report'))[1].signal;
    view.rerender(<ResearchScanPanel onImportReport={onImportReport} onBusy={onBusy} resetKey={1} />);
    expect(signal.aborted).toBe(true);
    await act(async () => { pending.resolve({ data: reportBundle() }); });
    expect(onImportReport).not.toHaveBeenCalled();
    expect(screen.getByRole('heading', { name: 'Scan status: completed' })).toBeTruthy();
    expect(onBusy.mock.calls).toEqual([[true], [false]]);
  });

  test('a session failure clears scan state and stops further automatic checks', async () => {
    await mount(); await startScan('completed');
    api.get.mockRejectedValueOnce({ response: { status: 401, data: { detail: { message: 'PRIVATE_SERVER_MESSAGE' } } } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh saved scans' })); });
    expect(screen.queryByTestId('selected-scan')).toBeNull();
    expect(screen.getByLabelText('Search query').value).toBe('');
    expect(screen.getByRole('alert').textContent).toContain('session has expired');
    expect(screen.queryByText(/PRIVATE_SERVER_MESSAGE/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Start scan', exact: true }).disabled).toBe(true);
  });

  test('a newer selected run suppresses an older status response', async () => {
    await mount();
    api.get.mockResolvedValueOnce({ data: { runs: [run('completed'), run('completed', secondId)] } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh saved scans' })); });
    const older = deferred(), newer = deferred();
    api.get.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    fireEvent.click(screen.getByRole('button', { name: `View scan ${id}` }));
    const signal = api.get.mock.calls.find(([url]) => url === `${endpoint}/${id}`)[1].signal;
    fireEvent.click(screen.getByRole('button', { name: `View scan ${secondId}` }));
    expect(signal.aborted).toBe(true);
    await act(async () => { newer.resolve({ data: { run: run('completed', secondId) } }); });
    await act(async () => { older.resolve({ data: { run: run('completed') } }); });
    expect(within(screen.getByTestId('selected-scan')).getByText(`Scan ${secondId}`)).toBeTruthy();
    expect(within(screen.getByTestId('selected-scan')).queryByText(`Scan ${id}`)).toBeNull();
  });

  test('unmount aborts report requests and suppresses late parent callbacks', async () => {
    const onImportReport = jest.fn(), pending = deferred();
    const view = await mount({ onImportReport }); await startScan('completed');
    api.get.mockReturnValueOnce(pending.promise);
    fireEvent.click(screen.getByRole('button', { name: 'Open retained report' }));
    const signal = api.get.mock.calls.find(([url]) => url.endsWith('/report'))[1].signal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => { pending.resolve({ data: reportBundle() }); });
    expect(onImportReport).not.toHaveBeenCalled();
  });
});
