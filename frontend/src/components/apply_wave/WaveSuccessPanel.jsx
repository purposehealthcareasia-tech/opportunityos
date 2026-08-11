import React from 'react';

/**
 * Success panel rendered inside <ApplyWaveCapsule/> after a successful
 * POST /wave/authorize.
 *
 * Split out from `ApplyWaveCapsule.jsx` on 2026-08-11 as part of the P2
 * Tier-2 component split. Testids preserved verbatim:
 *   apply-wave-success · apply-wave-close-success
 *
 * Zero behaviour change intended.
 */
export function WaveSuccessPanel({ wave, onClose }) {
  return (
    <div
      className="rounded-md border border-teal-500/25 bg-teal-500/5 p-3 text-xs"
      data-testid="apply-wave-success"
    >
      <div className="font-medium">
        Queued {wave.queued_count} application{wave.queued_count === 1 ? '' : 's'}. Authorization logged.
      </div>
      <div className="muted mt-1">
        Standing Wave: {wave.standing_wave ? 'ON — future arrivals auto-queue' : 'OFF'}
      </div>
      {wave.blocked_at_shortlist && wave.blocked_at_shortlist.length > 0 && (
        <div className="mt-2">
          {wave.blocked_at_shortlist.length} job{wave.blocked_at_shortlist.length === 1 ? '' : 's'} blocked at shortlist (cap or duplicate).
        </div>
      )}
      <button
        type="button"
        className="btn btn-sm btn-ghost mt-2"
        onClick={onClose}
        data-testid="apply-wave-close-success"
      >
        Close
      </button>
    </div>
  );
}
