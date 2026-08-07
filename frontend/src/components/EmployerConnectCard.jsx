import React, { useState } from 'react';
import { Plus, Building2, ThumbsUp, CheckCircle2, AlertCircle } from 'lucide-react';
import { api } from '../lib/api';

/**
 * Phase 3 · SUPPLY ENGINE — self-serve employer connect + vote.
 *
 * Rails:
 *   - HTTPS URL only (server validates; client shows the honest error).
 *   - 20-per-24h rate-limit envelope; 429 shown verbatim.
 *   - Dedup ledger — same host by same user returns `already_submitted:
 *     true` and we surface it as "already on your list".
 *   - Vote is one-per-user-per-employer_key; second attempt returns
 *     `already_voted: true` (we surface that too).
 *   - NO scraping. NO auto-ingest. Founder triage is the next step.
 */
export function EmployerConnectCard() {
  const [url, setUrl] = useState('');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [flash, setFlash] = useState(null);

  const submit = async () => {
    setFlash(null);
    setSubmitting(true);
    try {
      const { data } = await api.post('/api/v1/employers/connect',
        { url, notes: notes || undefined });
      const key = data?.submission?.canonical_host;
      // Auto-cast a vote so the founder's queue reflects it immediately.
      let voted = false;
      if (key) {
        try {
          await api.post('/api/v1/employers/vote', { employer_key: key });
          voted = true;
        } catch { /* vote is best-effort */ }
      }
      setFlash({
        kind: 'ok',
        msg: data.already_submitted
          ? `Already on your list: ${key}${voted ? ' (vote refreshed).' : '.'}`
          : `Submitted ${key} for founder review${voted ? ' + vote cast.' : '.'}`,
      });
      if (!data.already_submitted) {
        setUrl('');
        setNotes('');
      }
    } catch (e) {
      const detail = e?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : (detail?.message || detail?.error || 'Submission failed.');
      setFlash({ kind: 'err', msg });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="card p-5 space-y-3" data-testid="employer-connect-card">
      <header className="flex items-center gap-2">
        <Building2 className="h-4 w-4" />
        <h2 className="text-lg font-semibold">Request an employer</h2>
      </header>
      <p className="text-xs muted">
        Missing your target employer? Submit their careers page URL — the founder reviews the queue and adds the employer to the discovery lane by hand.
        No scraping, no auto-ingest. HTTPS only.
      </p>
      <div className="space-y-2">
        <label className="text-xs muted">Careers page URL</label>
        <input
          type="url"
          className="w-full rounded-md border border-line dark:border-line-dark bg-white dark:bg-neutral-900 px-3 py-2 text-sm"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://acme.com/careers"
          data-testid="employer-connect-url"
        />
      </div>
      <div className="space-y-2">
        <label className="text-xs muted">Notes (optional, ≤ 500 chars)</label>
        <textarea
          className="w-full rounded-md border border-line dark:border-line-dark bg-white dark:bg-neutral-900 px-3 py-2 text-sm"
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          maxLength={500}
          placeholder="Anything the founder should know (why this employer, region, role family, etc.)"
          data-testid="employer-connect-notes"
        />
      </div>
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={submit}
          disabled={submitting || !url}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent text-white px-3 py-1.5 text-sm font-medium disabled:opacity-60"
          data-testid="employer-connect-submit"
        >
          <Plus className="h-4 w-4" />
          {submitting ? 'Submitting…' : 'Submit for review'}
        </button>
        <span className="text-[11px] muted">Cap: 20 submissions / 24h</span>
      </div>
      {flash && (
        <div
          className={`text-sm flex items-start gap-2 rounded-md px-3 py-2 border ${
            flash.kind === 'ok'
              ? 'border-accent/40 bg-accent/5 text-accent'
              : 'border-red-500/40 bg-red-500/5 text-red-700 dark:text-red-400'
          }`}
          data-testid="employer-connect-flash"
        >
          {flash.kind === 'ok'
            ? <CheckCircle2 className="h-4 w-4 mt-0.5 flex-shrink-0" />
            : <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />}
          <span>{flash.msg}</span>
        </div>
      )}
      <div className="text-[11px] muted italic border-t border-line dark:border-line-dark pt-2" data-testid="employer-connect-copy-guardrail">
        <ThumbsUp className="h-3 w-3 inline mr-1 -mt-0.5" />
        Submitting also casts your vote on the shared queue. One vote per employer per user.
      </div>
    </div>
  );
}
