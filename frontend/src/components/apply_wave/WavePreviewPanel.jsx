import React from 'react';

/**
 * Preview panel rendered inside <ApplyWaveCapsule/> when we have a
 * dry-run preview response and no successful `wave` yet.
 *
 * Split out from `ApplyWaveCapsule.jsx` on 2026-08-11 as part of the P2
 * Tier-2 component split. All testids preserved verbatim:
 *   apply-wave-preview · wave-breakdown-* · wave-eligible-list
 *   apply-wave-standing-toggle · apply-wave-confirm ·
 *   apply-wave-cancel · apply-wave-refresh
 *
 * State (busy / standing / preview) is owned by the parent and passed
 * in. The parent also owns the async action handlers (`onAuthorize`,
 * `onCancel`, `onRefresh`). Zero behaviour change intended.
 */
export function WavePreviewPanel({
  preview,
  busy,
  standing,
  onStandingChange,
  onAuthorize,
  onCancel,
  onRefresh,
}) {
  return (
    <div
      className="rounded-md border border-line dark:border-line-dark p-3 space-y-2"
      data-testid="apply-wave-preview"
    >
      <div className="text-xs font-medium">
        Would queue {preview.eligible_count} of {preview.breakdown.total_scanned} scanned
      </div>
      <div className="text-[11px] muted grid grid-cols-2 gap-x-4 gap-y-0.5">
        <div>
          blocked by scope filter:{' '}
          <span data-testid="wave-breakdown-scope">{preview.breakdown.blocked_scope}</span>
        </div>
        <div>
          blocked by hard gate:{' '}
          <span data-testid="wave-breakdown-hard-gate">{preview.breakdown.blocked_hard_gate}</span>
        </div>
        <div>
          blocked by employer cap:{' '}
          <span data-testid="wave-breakdown-cap">{preview.breakdown.blocked_cap}</span>
        </div>
        <div>
          blocked as duplicate:{' '}
          <span data-testid="wave-breakdown-duplicate">{preview.breakdown.blocked_duplicate}</span>
        </div>
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
            <div className="text-[11px] muted">
              + {preview.eligible_summary.length - 20} more
            </div>
          )}
        </div>
      )}

      <label className="flex items-center gap-2 text-xs mt-2">
        <input
          type="checkbox"
          checked={standing}
          onChange={(e) => onStandingChange(e.target.checked)}
          data-testid="apply-wave-standing-toggle"
        />
        <span>
          Turn on Standing Wave — auto-queue matching new arrivals on future refresh cycles (cap still enforced).
        </span>
      </label>

      <div className="flex items-center gap-2 pt-1">
        <button
          type="button"
          disabled={busy || preview.eligible_count === 0}
          onClick={onAuthorize}
          className="btn btn-sm btn-primary"
          data-testid="apply-wave-confirm"
        >
          {busy ? 'Queueing…' : `Authorize wave (${preview.eligible_count} jobs)`}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="btn btn-sm btn-ghost"
          data-testid="apply-wave-cancel"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onRefresh}
          disabled={busy}
          className="btn btn-sm btn-ghost ml-auto"
          data-testid="apply-wave-refresh"
        >
          Re-preview
        </button>
      </div>
    </div>
  );
}
