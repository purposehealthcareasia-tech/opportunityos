import React, { useState } from 'react';
import { Waves, ShieldOff, AlertTriangle, Loader2 } from 'lucide-react';
import { api } from '../lib/api';

const BASE = '/api/v1/wave';

/**
 * Phase 1 §v (1b) — Apply Wave capsule.
 *
 * A user can:
 *   1. Preview the exact spectrum of jobs a wave WOULD queue right now
 *      (dry-run — never mutates state) via GET /wave/preview
 *   2. Confirm with an explicit click → POST /wave/authorize
 *      (persists a `wave_authorizations` row + shortlists eligible jobs)
 *   3. Toggle Standing Wave — when on, subsequent AAB refresh cycles
 *      auto-queue new arrivals matching the scope, still cap-respecting
 *
 * States rendered honestly:
 *   - closed (default) — collapsible entry point
 *   - opened / loading preview
 *   - preview rendered → confirm button (with cap breakdown)
 *   - authorized → success summary
 *   - 403 consent-revoked → explicit "consent required" message
 *   - preview error → error message + retry
 */
export default function ApplyWaveCapsule({ lane, withinMi, onWaved }) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [wave, setWave] = useState(null);            // POST authorize result
  const [standing, setStanding] = useState(false);

  const doPreview = async () => {
    setBusy(true); setErr(null); setWave(null);
    try {
      const params = new URLSearchParams();
      if (lane && lane !== 'all') params.set('lane', lane);
      if (withinMi != null) params.set('within_mi', String(withinMi));
      const q = params.toString() ? `?${params.toString()}` : '';
      const r = await api.get(`${BASE}/preview${q}`);
      setPreview(r.data);
    } catch (e) {
      if (e?.response?.status === 403) {
        setErr({ kind: 'consent', message: 'Apply Wave needs the "submit_applications" consent scope. Grant it in Settings to preview.' });
      } else {
        setErr({ kind: 'other', message: e?.response?.data?.detail || e.message || 'Preview failed.' });
      }
    } finally {
      setBusy(false);
    }
  };

  const doAuthorize = async () => {
    if (!preview) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.post(`${BASE}/authorize`, {
        lane: preview.scope.lane,
        within_mi: preview.scope.within_mi,
        family: preview.scope.family,
        cap: preview.scope.cap,
        standing_wave: !!standing,
      });
      setWave(r.data);
      setPreview(null);
      onWaved && onWaved();
    } catch (e) {
      setErr({ kind: 'other', message: e?.response?.data?.detail || e.message || 'Authorize failed.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="liquid-card p-4" data-testid="apply-wave-capsule">
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-full bg-teal-500/10 text-teal-500">
          <Waves className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <div className="text-sm font-semibold">Apply Wave</div>
            <span className="text-[10px] muted uppercase tracking-wider">§v · dry-run</span>
          </div>
          <div className="text-xs muted mt-1">
            One batch authorization queues every job passing your 3 hard gates + rolling 30-day per-employer cap, with a full preview first.
          </div>

          {!open && (
            <button
              type="button"
              className="btn btn-sm btn-outline mt-3"
              onClick={() => { setOpen(true); doPreview(); }}
              data-testid="apply-wave-open"
            >
              Preview what would queue
            </button>
          )}

          {open && (
            <div className="mt-3 space-y-3">
              {busy && !preview && !wave && (
                <div className="flex items-center gap-2 text-xs muted" data-testid="apply-wave-loading">
                  <Loader2 className="h-3 w-3 animate-spin" /> Enumerating spectrum…
                </div>
              )}

              {err?.kind === 'consent' && (
                <div className="flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/5 p-2.5 text-xs" data-testid="apply-wave-consent-required">
                  <ShieldOff className="h-3 w-3 mt-0.5 text-amber-500" />
                  <div>{err.message}</div>
                </div>
              )}
              {err?.kind === 'other' && (
                <div className="flex items-start gap-2 rounded-md border border-red-500/25 bg-red-500/5 p-2.5 text-xs" data-testid="apply-wave-error">
                  <AlertTriangle className="h-3 w-3 mt-0.5 text-red-500" />
                  <div>{String(err.message)}</div>
                </div>
              )}

              {preview && !wave && (
                <div className="rounded-md border border-line dark:border-line-dark p-3 space-y-2" data-testid="apply-wave-preview">
                  <div className="text-xs font-medium">Would queue {preview.eligible_count} of {preview.breakdown.total_scanned} scanned</div>
                  <div className="text-[11px] muted grid grid-cols-2 gap-x-4 gap-y-0.5">
                    <div>blocked by scope filter: <span data-testid="wave-breakdown-scope">{preview.breakdown.blocked_scope}</span></div>
                    <div>blocked by hard gate: <span data-testid="wave-breakdown-hard-gate">{preview.breakdown.blocked_hard_gate}</span></div>
                    <div>blocked by employer cap: <span data-testid="wave-breakdown-cap">{preview.breakdown.blocked_cap}</span></div>
                    <div>blocked as duplicate: <span data-testid="wave-breakdown-duplicate">{preview.breakdown.blocked_duplicate}</span></div>
                  </div>

                  {preview.eligible_count > 0 && (
                    <div className="mt-2 space-y-1 max-h-40 overflow-y-auto" data-testid="wave-eligible-list">
                      {preview.eligible_summary.slice(0, 20).map((j) => (
                        <div key={j.id} className="text-[11px] flex items-center gap-2">
                          <span className="text-teal-500">•</span>
                          <span className="font-medium truncate">{j.title || '(untitled)'}</span>
                          <span className="muted truncate">{j.company_name || ''}</span>
                        </div>
                      ))}
                      {preview.eligible_summary.length > 20 && (
                        <div className="text-[11px] muted">+ {preview.eligible_summary.length - 20} more</div>
                      )}
                    </div>
                  )}

                  <label className="flex items-center gap-2 text-xs mt-2">
                    <input
                      type="checkbox"
                      checked={standing}
                      onChange={(e) => setStanding(e.target.checked)}
                      data-testid="apply-wave-standing-toggle"
                    />
                    <span>Turn on Standing Wave — auto-queue matching new arrivals on future refresh cycles (cap still enforced).</span>
                  </label>

                  <div className="flex items-center gap-2 pt-1">
                    <button
                      type="button"
                      disabled={busy || preview.eligible_count === 0}
                      onClick={doAuthorize}
                      className="btn btn-sm btn-primary"
                      data-testid="apply-wave-confirm"
                    >
                      {busy ? 'Queueing…' : `Authorize wave (${preview.eligible_count} jobs)`}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setOpen(false); setPreview(null); setErr(null); setStanding(false); }}
                      className="btn btn-sm btn-ghost"
                      data-testid="apply-wave-cancel"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={doPreview}
                      disabled={busy}
                      className="btn btn-sm btn-ghost ml-auto"
                      data-testid="apply-wave-refresh"
                    >
                      Re-preview
                    </button>
                  </div>
                </div>
              )}

              {wave && (
                <div className="rounded-md border border-teal-500/25 bg-teal-500/5 p-3 text-xs" data-testid="apply-wave-success">
                  <div className="font-medium">Queued {wave.queued_count} application{wave.queued_count === 1 ? '' : 's'}. Authorization logged.</div>
                  <div className="muted mt-1">Standing Wave: {wave.standing_wave ? 'ON — future arrivals auto-queue' : 'OFF'}</div>
                  {wave.blocked_at_shortlist && wave.blocked_at_shortlist.length > 0 && (
                    <div className="mt-2">
                      {wave.blocked_at_shortlist.length} job{wave.blocked_at_shortlist.length === 1 ? '' : 's'} blocked at shortlist (cap or duplicate).
                    </div>
                  )}
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost mt-2"
                    onClick={() => { setOpen(false); setWave(null); }}
                    data-testid="apply-wave-close-success"
                  >
                    Close
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
