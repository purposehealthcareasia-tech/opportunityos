import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../lib/api';
import FyndJobResearchImport from './FyndJobResearchImport';

jest.mock('../lib/api', () => ({ api: { get: jest.fn() } }));
const JOB_ID = '1393c281-2d9f-4ed8-a38f-16b7c4b02f6d';
const SECOND_ID = '2493c281-2d9f-4ed8-a38f-16b7c4b02f6d';
const ROUTER_FUTURE = { v7_startTransition: true, v7_relativeSplatPath: true };
const job = (extra = {}) => ({ id: JOB_ID, title: 'Research engineer', company_name: 'Example company', origin_url: 'https://example.org/careers/research', apply_url: 'https://example.org/apply/private-reference', jd_text: 'A retained job description.', source: 'greenhouse', status: 'active', is_sample: false, needs_origin: false, posted_at: '2026-09-01T10:00:00Z', last_verified: '2026-09-02T12:00:00Z', score: 99, gates: ['private gate'], have_gap: ['private skill gap'], ...extra });
function setup(props = {}, path = '/research') {
  const onReport = props.onReport || jest.fn();
  const rendered = render(<MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}><FyndJobResearchImport onReport={onReport} {...props} /></MemoryRouter>);
  return { ...rendered, onReport };
}
function enter(value = JOB_ID) {
  fireEvent.change(screen.getByLabelText('Fynd job ID or internal path'), { target: { value } });
}
function load() { fireEvent.click(screen.getByRole('button', { name: 'Load Fynd job', exact: true })); }
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }

describe('Fynd stored-job research import', () => {
  beforeEach(() => { api.get.mockReset(); });

  test('prefills a strict deep-link UUID without automatically reading any API', () => {
    setup({}, `/research?job=${JOB_ID}`);
    expect(screen.getByLabelText('Fynd job ID or internal path').value).toBe(JOB_ID);
    expect(api.get).not.toHaveBeenCalled();
    expect(screen.getByText(/nothing loads until you choose/)).toBeTruthy();
  });

  test('rejects invalid and duplicated deep-link IDs without API calls', () => {
    const view = setup({}, '/research?job=https%3A%2F%2Fexample.org%2Fjobs');
    expect(screen.getByRole('alert').textContent).toMatch(/invalid Fynd job ID/);
    expect(api.get).not.toHaveBeenCalled();
    view.unmount();
    setup({}, `/research?job=${JOB_ID}&job=${SECOND_ID}`);
    expect(screen.getByRole('alert').textContent).toMatch(/invalid Fynd job ID/);
    expect(api.get).not.toHaveBeenCalled();
  });

  test('imports an explicit internal job path through the existing API and excludes personal/application fields', async () => {
    api.get.mockResolvedValue({ data: job() });
    const { onReport } = setup();
    enter(`/jobs/${JOB_ID}`); load();
    await waitFor(() => expect(onReport).toHaveBeenCalledTimes(1));
    expect(api.get).toHaveBeenCalledWith(`/api/v1/jobs/${JOB_ID}`, expect.objectContaining({ signal: expect.anything(), timeout: 15000 }));
    const report = onReport.mock.calls[0][0], record = report.records[0];
    expect(report.records).toHaveLength(1);
    expect(record.kind).toBe('jobs');
    expect(record.contentStatus).toBe('unknown');
    expect(record.content).toBe('A retained job description.');
    expect(record.url).toBe(job().origin_url);
    expect(record.sourceId).toBe(JOB_ID);
    expect(report.omissions.join(' ')).toMatch(/original website was not fetched/);
    expect(report.warnings.join(' ')).toMatch(/No new verification/);
    const serialized = JSON.stringify(report);
    expect(serialized).not.toContain('private-reference');
    expect(serialized).not.toContain('private gate');
    expect(serialized).not.toContain('private skill gap');
    expect(serialized).not.toContain('"score":99');
    expect(screen.getByRole('status').textContent).toMatch(/not fetched or reverified/);
  });

  test('retains a bodyless job as metadata-only', async () => {
    api.get.mockResolvedValue({ data: job({ jd_text: null }) });
    const { onReport } = setup(); enter(); load();
    await waitFor(() => expect(onReport).toHaveBeenCalledTimes(1));
    expect(onReport.mock.calls[0][0].records[0].contentStatus).toBe('metadata-only');
  });

  test.each(['https://fynd.llc/jobs/' + JOB_ID, '/jobs/' + JOB_ID + '?x=1', '../jobs/' + JOB_ID, 'not-a-uuid', '/jobs/' + JOB_ID + '/extra'])('rejects non-internal identifiers without fetching: %s', value => {
    setup(); enter(value); load();
    expect(screen.getByRole('alert').textContent).toMatch(/External job links are not supported/);
    expect(api.get).not.toHaveBeenCalled();
  });

  test.each([
    [{ is_sample: true }, /Sample jobs/],
    [{ is_sample: undefined }, /does not declare whether it is a sample/],
    [{ origin_url: '' }, /no usable original source/],
    [{ origin_url: null, apply_url: 'https://example.org/apply' }, /will not be substituted/],
    [{ needs_origin: true }, /no usable original source/],
    [{ origin_url: 'javascript:alert(1)' }, /unsafe or unsupported/],
    [{ origin_url: 'http://127.0.0.1/private' }, /unsafe or unsupported/],
    [{ origin_url: 'https://user:password@example.org/private' }, /unsafe or unsupported/],
    [{ id: SECOND_ID }, /different or invalid job record/],
    [{ jd_text: 'x'.repeat(60001) }, /too large/],
  ])('rejects unusable stored evidence without replacing a report', async (extra, message) => {
    api.get.mockResolvedValue({ data: job(extra) });
    const { onReport } = setup(); enter(); load();
    expect((await screen.findByRole('alert')).textContent).toMatch(message);
    expect(onReport).not.toHaveBeenCalled();
  });

  test.each([
    [{ response: { status: 401, data: { detail: 'secret server trace' } } }, /Sign in again/],
    [{ response: { status: 403, data: { detail: { code: 'consent_required', secret: 'secret server trace' } } } }, /required career-data consent/],
    [{ response: { status: 404 } }, /could not be found/],
    [{ code: 'ECONNABORTED', message: 'secret server trace' }, /too long to respond/],
    [{ response: { status: 503 } }, /temporarily unavailable/],
    [{ response: { status: 500, data: { detail: 'secret server trace' } } }, /could not be loaded/],
  ])('maps network errors to safe messages and preserves existing reports', async (error, message) => {
    api.get.mockRejectedValue(error);
    const { onReport } = setup(); enter(); load();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(message);
    expect(alert.textContent).not.toContain('secret server trace');
    expect(onReport).not.toHaveBeenCalled();
  });

  test('clear aborts pending reads and ignores a late success even if the client ignores abort', async () => {
    const pending = deferred(); api.get.mockReturnValue(pending.promise);
    const { onReport } = setup(); enter(); load();
    const signal = api.get.mock.calls[0][1].signal;
    fireEvent.click(screen.getByRole('button', { name: 'Clear job input' }));
    expect(signal.aborted).toBe(true);
    await act(async () => { pending.resolve({ data: job() }); await pending.promise; });
    expect(onReport).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Fynd job ID or internal path').value).toBe('');
    expect(screen.queryByRole('status')).toBeNull();
  });

  test('new input and request supersede an older response', async () => {
    const old = deferred(), next = deferred(); api.get.mockReturnValueOnce(old.promise).mockReturnValueOnce(next.promise);
    const { onReport } = setup(); enter(); load();
    const firstSignal = api.get.mock.calls[0][1].signal;
    enter(SECOND_ID); load();
    expect(firstSignal.aborted).toBe(true);
    await act(async () => { next.resolve({ data: job({ id: SECOND_ID, title: 'Second job' }) }); await next.promise; });
    await act(async () => { old.resolve({ data: job() }); await old.promise; });
    expect(onReport).toHaveBeenCalledTimes(1);
    expect(onReport.mock.calls[0][0].records[0].sourceId).toBe(SECOND_ID);
  });

  test('unmount aborts and suppresses late errors and reports', async () => {
    const pending = deferred(); api.get.mockReturnValue(pending.promise);
    const onBusy = jest.fn();
    const { onReport, unmount } = setup({ onBusy }); enter(); load();
    const signal = api.get.mock.calls[0][1].signal;
    unmount(); expect(signal.aborted).toBe(true);
    expect(onBusy).toHaveBeenLastCalledWith(false);
    await act(async () => { pending.resolve({ data: job() }); await pending.promise; });
    expect(onReport).not.toHaveBeenCalled();
  });

  test('parent resetKey cancels a pending read without clearing the parent report', async () => {
    const pending = deferred(); api.get.mockReturnValue(pending.promise);
    const onReport = jest.fn(), onBusy = jest.fn();
    const { rerender } = setup({ onReport, onBusy, resetKey: 1 }); enter(); load();
    expect(onBusy).toHaveBeenCalledWith(true);
    const signal = api.get.mock.calls[0][1].signal;
    rerender(<MemoryRouter future={ROUTER_FUTURE}><FyndJobResearchImport onReport={onReport} onBusy={onBusy} resetKey={2} /></MemoryRouter>);
    expect(signal.aborted).toBe(true);
    await act(async () => { pending.resolve({ data: job() }); await pending.promise; });
    expect(onReport).not.toHaveBeenCalled();
    expect(onBusy).toHaveBeenLastCalledWith(false);
  });
});
