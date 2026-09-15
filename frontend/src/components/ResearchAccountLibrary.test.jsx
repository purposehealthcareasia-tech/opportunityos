import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '../lib/api';
import { ResearchAccountError, accountSnapshot, reopenSavedSnapshot, validateAccountListing, validateSavedReceipt, validateDeleteReceipt } from '../lib/researchAccount';
import ResearchAccountLibrary from './ResearchAccountLibrary';

jest.mock('../lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), delete: jest.fn() } }));
jest.mock('../lib/researchAccount', () => ({
  ResearchAccountError: jest.requireActual('../lib/researchAccount').ResearchAccountError,
  accountSnapshot: jest.fn(), reopenSavedSnapshot: jest.fn(), validateAccountListing: jest.fn(), validateSavedReceipt: jest.fn(), validateDeleteReceipt: jest.fn(),
}));

const endpoint = '/api/v1/research/reports';
const first = { id: '11111111-1111-4111-8111-111111111111', title: 'Saved evidence one', saved_at: '2026-09-13T09:00:00Z', byte_size: 400 };
const second = { id: '22222222-2222-4222-8222-222222222222', title: 'Saved evidence two', saved_at: '2026-09-13T10:00:00Z', byte_size: 500 };
const listing = { reports: [first, second], used_bytes: 900, limits: { max_reports: 20, max_report_bytes: 8388608, max_total_bytes: 10485760 } };
const localReport = { id: 'local-report', title: 'Local evidence', records: [] };
const snapshot = { manifest: { schemaVersion: 1, title: 'Local evidence' }, files: {} };
const savedMetadata = { ...first, title: snapshot.manifest.title, byte_size: new Blob([JSON.stringify(snapshot)]).size };
const reopened = { id: 'reopened-report', title: 'Reopened evidence', records: [] };
const detail = { report: { ...first, bundle: snapshot } };

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function acknowledge() { fireEvent.click(screen.getByRole('checkbox', { name: 'I want to store this report in my Fynd account' })); }
function saveReport() { acknowledge(); fireEvent.click(screen.getByRole('button', { name: 'Save report', exact: true })); }
async function showListing() {
  api.get.mockResolvedValueOnce({ data: listing });
  fireEvent.click(screen.getByRole('button', { name: 'Saved reports', exact: true }));
  await screen.findByRole('heading', { name: first.title });
}
function openSaved(item = first) { fireEvent.click(screen.getByRole('button', { name: `Open saved report: ${item.title}` })); }

describe('ResearchAccountLibrary explicit storage', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    accountSnapshot.mockReturnValue(snapshot);
    reopenSavedSnapshot.mockReturnValue(reopened);
    validateAccountListing.mockImplementation(value => value);
    validateSavedReceipt.mockImplementation(value => value);
    validateDeleteReceipt.mockImplementation(value => value);
  });

  test('does not fetch or persist on mount or report changes and explains storage limits', () => {
    const { rerender } = render(<ResearchAccountLibrary report={localReport} resetKey={0} />);
    rerender(<ResearchAccountLibrary report={{ ...localReport, id: 'replacement' }} resetKey={1} />);

    expect(api.get).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
    expect(api.delete).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Save report', exact: true }).disabled).toBe(true);
    expect(screen.getByText(/8 MiB per report, 10 MiB total, and 20 saved reports/)).toBeTruthy();
    expect(screen.getByText(/Saving explicitly uploads a report snapshot to your private Fynd account/)).toBeTruthy();
    expect(screen.getByText(/it may still finish on the server/)).toBeTruthy();
  });

  test('requires an open report and explicit upload acknowledgement before saving', async () => {
    const { rerender } = render(<ResearchAccountLibrary report={null} />);
    expect(screen.getByRole('checkbox').disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Save report', exact: true }));
    expect(api.post).not.toHaveBeenCalled();

    rerender(<ResearchAccountLibrary report={localReport} />);
    expect(screen.getByRole('checkbox').disabled).toBe(false);
    expect(screen.getByRole('button', { name: 'Save report', exact: true }).disabled).toBe(true);
    api.post.mockResolvedValueOnce({ data: { report: savedMetadata, replay: false } });
    saveReport();

    await screen.findByText(/Report snapshot saved in your Fynd account/);
    expect(accountSnapshot).toHaveBeenCalledWith(localReport);
    expect(api.post).toHaveBeenCalledWith(endpoint, { bundle: snapshot, confirm_storage: true }, expect.objectContaining({ timeout: 20000, signal: expect.anything() }));
    expect(validateSavedReceipt).toHaveBeenCalledWith({ report: savedMetadata, replay: false });
    expect(screen.getByRole('checkbox').checked).toBe(false);
    expect(api.get).not.toHaveBeenCalled();
  });

  test('a changed report clears its upload acknowledgement', () => {
    const { rerender } = render(<ResearchAccountLibrary report={localReport} resetKey={0} />);
    acknowledge();
    expect(screen.getByRole('checkbox').checked).toBe(true);
    rerender(<ResearchAccountLibrary report={{ ...localReport, id: 'new' }} resetKey={0} />);
    expect(screen.getByRole('checkbox').checked).toBe(false);
    expect(screen.getByRole('button', { name: 'Save report', exact: true }).disabled).toBe(true);
  });

  test('rejects an oversized or invalid snapshot locally without uploading it', async () => {
    accountSnapshot.mockImplementation(() => { throw new ResearchAccountError('ACCOUNT_REPORT_TOO_LARGE', 'This snapshot exceeds 8 MiB. Download a local copy instead.'); });
    render(<ResearchAccountLibrary report={localReport} />);
    saveReport();

    expect((await screen.findByRole('alert')).textContent).toContain('exceeds 8 MiB');
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.queryByText(/Report snapshot saved in your Fynd account/)).toBeNull();
  });

  test('lists metadata only after a click and does not mark list or save operations as imports', async () => {
    const onBusy = jest.fn(), onReport = jest.fn();
    render(<ResearchAccountLibrary report={localReport} onReport={onReport} onBusy={onBusy} />);
    await showListing();

    expect(api.get).toHaveBeenCalledWith(endpoint, expect.objectContaining({ timeout: 15000, signal: expect.anything() }));
    expect(validateAccountListing).toHaveBeenCalledWith(listing);
    expect(screen.getByText(/2 saved reports/)).toBeTruthy();
    expect(onReport).not.toHaveBeenCalled();
    expect(onBusy).not.toHaveBeenCalled();

    api.post.mockResolvedValueOnce({ data: { report: savedMetadata, replay: true } });
    saveReport();
    await screen.findByText(/already saved in your Fynd account/);
    expect(onBusy).not.toHaveBeenCalled();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  test('validates a saved detail with its expected ID before passing it to the parent', async () => {
    const onReport = jest.fn(), onBusy = jest.fn();
    render(<ResearchAccountLibrary report={localReport} onReport={onReport} onBusy={onBusy} />);
    await showListing();
    api.get.mockResolvedValueOnce({ data: detail });
    openSaved();

    await waitFor(() => expect(onReport).toHaveBeenCalledWith(reopened));
    expect(reopenSavedSnapshot).toHaveBeenCalledWith(detail, first.id);
    expect(api.get).toHaveBeenLastCalledWith(`${endpoint}/${first.id}`, expect.objectContaining({ timeout: 20000 }));
    expect(onBusy.mock.calls).toEqual([[true], [false]]);
    expect(screen.getByText(/Its sources were not fetched or independently verified/)).toBeTruthy();
  });

  test('a malformed saved response does not replace the open report', async () => {
    const onReport = jest.fn();
    reopenSavedSnapshot.mockImplementation(() => { throw new ResearchAccountError('ACCOUNT_INVALID_SNAPSHOT', 'The saved report failed validation. Your open report is unchanged.'); });
    render(<ResearchAccountLibrary report={localReport} onReport={onReport} />);
    await showListing();
    api.get.mockResolvedValueOnce({ data: { report: { ...second, bundle: {} } } });
    openSaved();

    expect((await screen.findByRole('alert')).textContent).toContain('failed validation');
    expect(onReport).not.toHaveBeenCalled();
    expect(screen.queryByText(/Saved snapshot opened/)).toBeNull();
  });

  test.each([
    [401, 'session has expired'], [403, 'not authorized'], [404, 'saved report is unavailable'],
    [413, 'exceeds an account-storage limit'], [429, 'Too many account requests'], [503, 'temporarily unavailable'],
  ])('renders a friendly %s response without exposing backend details', async (status, expected) => {
    api.get.mockRejectedValueOnce({ response: { status, data: { detail: 'SECRET_BACKEND_TRACE' } }, message: 'SECRET_BACKEND_TRACE' });
    render(<ResearchAccountLibrary report={localReport} />);
    fireEvent.click(screen.getByRole('button', { name: 'Saved reports', exact: true }));

    expect((await screen.findByRole('alert')).textContent).toContain(expected);
    expect(screen.queryByText(/SECRET_BACKEND_TRACE/)).toBeNull();
  });

  test('requires inline confirmation before deleting and leaves the open report alone', async () => {
    const onReport = jest.fn(), onBusy = jest.fn();
    render(<ResearchAccountLibrary report={localReport} onReport={onReport} onBusy={onBusy} />);
    await showListing();
    fireEvent.click(screen.getByRole('button', { name: `Delete saved report: ${first.title}` }));
    expect(api.delete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Keep saved report' }));
    expect(screen.queryByRole('button', { name: `Confirm delete: ${first.title}` })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: `Delete saved report: ${first.title}` }));
    api.delete.mockResolvedValueOnce({ data: { deleted: true } });
    fireEvent.click(screen.getByRole('button', { name: `Confirm delete: ${first.title}` }));

    await screen.findByText(/Saved account copy deleted/);
    expect(api.delete).toHaveBeenCalledWith(`${endpoint}/${first.id}`, expect.objectContaining({ timeout: 15000, signal: expect.anything() }));
    expect(validateDeleteReceipt).toHaveBeenCalledWith({ deleted: true });
    expect(screen.queryByRole('heading', { name: first.title })).toBeNull();
    expect(screen.getByRole('heading', { name: second.title })).toBeTruthy();
    expect(onReport).not.toHaveBeenCalled();
    expect(onBusy).not.toHaveBeenCalled();
  });

  test('does not remove list entries when a delete receipt fails validation', async () => {
    validateDeleteReceipt.mockImplementation(() => { throw new ResearchAccountError('ACCOUNT_INVALID_RESPONSE', 'Deletion could not be confirmed. Refresh Saved reports.'); });
    render(<ResearchAccountLibrary report={localReport} />);
    await showListing();
    fireEvent.click(screen.getByRole('button', { name: `Delete saved report: ${first.title}` }));
    api.delete.mockResolvedValueOnce({ data: { deleted: false } });
    fireEvent.click(screen.getByRole('button', { name: `Confirm delete: ${first.title}` }));

    await screen.findByRole('alert');
    expect(screen.getByRole('heading', { name: first.title })).toBeTruthy();
    expect(screen.queryByText(/Saved account copy deleted/)).toBeNull();
  });

  test('uncertain save failures do not claim the server write was canceled', async () => {
    api.post.mockRejectedValueOnce(new Error('private server trace'));
    render(<ResearchAccountLibrary report={localReport} />);
    saveReport();

    expect((await screen.findByRole('alert')).textContent).toContain('It may have completed');
    expect(screen.queryByText(/private server trace/)).toBeNull();
    expect(screen.queryByText(/write was canceled/)).toBeNull();
  });

  test('a save receipt must match the submitted title before success is shown', async () => {
    api.post.mockResolvedValueOnce({ data: { report: { ...savedMetadata, title: 'A different report' }, replay: false } });
    render(<ResearchAccountLibrary report={localReport} />);
    saveReport();

    expect((await screen.findByRole('alert')).textContent).toContain('inconsistent saved-report details');
    expect(screen.queryByText(/Report snapshot saved in your Fynd account/)).toBeNull();
  });

  test('accepts a valid server canonical byte size that differs from browser serialization', async () => {
    validateSavedReceipt.mockImplementation(jest.requireActual('../lib/researchAccount').validateSavedReceipt);
    api.post.mockResolvedValueOnce({ data: { report: { ...savedMetadata, byte_size: savedMetadata.byte_size + 2 }, replay: false } });
    render(<ResearchAccountLibrary report={localReport} />);
    saveReport();

    await screen.findByText(/Report snapshot saved in your Fynd account/);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  test.each([0, 8388609, 1.5])('rejects malformed or out-of-bounds saved byte_size %s', async byteSize => {
    validateSavedReceipt.mockImplementation(jest.requireActual('../lib/researchAccount').validateSavedReceipt);
    api.post.mockResolvedValueOnce({ data: { report: { ...savedMetadata, byte_size: byteSize }, replay: false } });
    render(<ResearchAccountLibrary report={localReport} />);
    saveReport();

    expect((await screen.findByRole('alert')).textContent).toContain('invalid saved-report response');
    expect(screen.queryByText(/Report snapshot saved in your Fynd account/)).toBeNull();
  });

  test('a late save cannot mark a replacement report as saved', async () => {
    const pending = deferred();
    api.post.mockReturnValueOnce(pending.promise);
    const { rerender } = render(<ResearchAccountLibrary report={localReport} resetKey={0} />);
    saveReport();
    const signal = api.post.mock.calls[0][2].signal;
    rerender(<ResearchAccountLibrary report={{ ...localReport, id: 'replacement' }} resetKey={1} />);
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve({ data: { report: savedMetadata, replay: false } }));

    expect(validateSavedReceipt).not.toHaveBeenCalled();
    expect(screen.queryByText(/Report snapshot saved in your Fynd account/)).toBeNull();
    expect(screen.getByRole('checkbox').checked).toBe(false);
  });

  test('a reset invalidates an account load and keeps a late response out of the parent', async () => {
    const pending = deferred(), onReport = jest.fn(), onBusy = jest.fn();
    const { rerender } = render(<ResearchAccountLibrary report={localReport} onReport={onReport} onBusy={onBusy} resetKey={0} />);
    await showListing();
    api.get.mockReturnValueOnce(pending.promise);
    openSaved();
    const signal = api.get.mock.calls[1][1].signal;
    rerender(<ResearchAccountLibrary report={localReport} onReport={onReport} onBusy={onBusy} resetKey={1} />);
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve({ data: detail }));

    expect(onReport).not.toHaveBeenCalled();
    expect(reopenSavedSnapshot).not.toHaveBeenCalled();
    expect(onBusy.mock.calls).toEqual([[true], [false]]);
    expect(screen.queryByText(/Saved snapshot opened/)).toBeNull();
  });

  test('a newer account load aborts the older request and only opens the newer result', async () => {
    const older = deferred(), newer = deferred(), onReport = jest.fn();
    render(<ResearchAccountLibrary report={localReport} onReport={onReport} />);
    await showListing();
    api.get.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    openSaved(first);
    const olderSignal = api.get.mock.calls[1][1].signal;
    openSaved(second);
    expect(olderSignal.aborted).toBe(true);
    const newerDetail = { report: { ...second, bundle: snapshot } };
    await act(async () => newer.resolve({ data: newerDetail }));
    await act(async () => older.resolve({ data: detail }));

    expect(onReport).toHaveBeenCalledTimes(1);
    expect(reopenSavedSnapshot).toHaveBeenCalledTimes(1);
    expect(reopenSavedSnapshot).toHaveBeenCalledWith(newerDetail, second.id);
  });

  test('unmount aborts an account load and suppresses late errors and callbacks', async () => {
    const pending = deferred(), onReport = jest.fn(), onBusy = jest.fn();
    const { unmount } = render(<ResearchAccountLibrary report={localReport} onReport={onReport} onBusy={onBusy} />);
    await showListing();
    api.get.mockReturnValueOnce(pending.promise);
    openSaved();
    const signal = api.get.mock.calls[1][1].signal;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => pending.reject({ response: { status: 503 } }));

    expect(onReport).not.toHaveBeenCalled();
    expect(onBusy.mock.calls).toEqual([[true], [false]]);
  });

  test('an invalid list does not become actionable saved-report rows', async () => {
    validateAccountListing.mockImplementation(() => { throw new ResearchAccountError('ACCOUNT_INVALID_RESPONSE', 'The saved report list failed validation.'); });
    api.get.mockResolvedValueOnce({ data: { reports: [{ ...first, id: '../admin' }] } });
    render(<ResearchAccountLibrary report={localReport} />);
    fireEvent.click(screen.getByRole('button', { name: 'Saved reports', exact: true }));

    await screen.findByRole('alert');
    expect(screen.queryByRole('heading', { name: first.title })).toBeNull();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  test('round-trips a real compact snapshot through validated account responses', async () => {
    const actual = jest.requireActual('../lib/researchAccount');
    const { buildReport } = jest.requireActual('../lib/researchReport');
    accountSnapshot.mockImplementation(actual.accountSnapshot);
    reopenSavedSnapshot.mockImplementation(actual.reopenSavedSnapshot);
    validateAccountListing.mockImplementation(actual.validateAccountListing);
    validateSavedReceipt.mockImplementation(actual.validateSavedReceipt);
    const realReport = buildReport({ title: 'Real-contract fixture', records: [{ url: 'https://example.org/evidence', title: 'Retained fixture source', kind: 'paper', content: 'Synthetic retained evidence body.', contentStatus: 'partial' }] });
    const realBundle = actual.accountSnapshot(realReport);
    const realMetadata = { ...first, title: realBundle.manifest.title, byte_size: new Blob([JSON.stringify(realBundle)]).size };
    const onReport = jest.fn();
    render(<ResearchAccountLibrary report={realReport} onReport={onReport} />);
    api.post.mockResolvedValueOnce({ data: { report: realMetadata, replay: false } });
    saveReport();
    await screen.findByText(/Report snapshot saved in your Fynd account/);

    api.get.mockResolvedValueOnce({ data: { reports: [realMetadata], used_bytes: realMetadata.byte_size, limits: actual.ACCOUNT_LIMITS } });
    fireEvent.click(screen.getByRole('button', { name: 'Saved reports', exact: true }));
    await screen.findByRole('heading', { name: realMetadata.title });
    api.get.mockResolvedValueOnce({ data: { report: { ...realMetadata, bundle: realBundle } } });
    openSaved(realMetadata);
    await waitFor(() => expect(onReport).toHaveBeenCalledTimes(1));

    expect(onReport.mock.calls[0][0].title).toBe(realReport.title);
    expect(onReport.mock.calls[0][0].records[0].url).toBe('https://example.org/evidence');
    expect(onReport.mock.calls[0][0].records[0].contentStatus).toBe('partial');
    expect(onReport.mock.calls[0][0].records[0].content).toBe('Synthetic retained evidence body.');
  });
});
