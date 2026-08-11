import React from 'react';
import { ShieldOff, AlertTriangle } from 'lucide-react';

/**
 * Error blocks rendered inside <ApplyWaveCapsule/>.
 *
 * Split out from `ApplyWaveCapsule.jsx` on 2026-08-11 as part of the P2
 * Tier-2 component split. Behaviour is byte-identical to the previous
 * inline JSX — same testids, same copy, same conditionals. Consumers
 * only render <WaveErrorBlocks err={err}/>.
 */
export function WaveErrorBlocks({ err }) {
  if (!err) return null;
  if (err.kind === 'consent') {
    return (
      <div
        className="flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/5 p-2.5 text-xs"
        data-testid="apply-wave-consent-required"
      >
        <ShieldOff className="h-3 w-3 mt-0.5 text-amber-500" />
        <div>{err.message}</div>
      </div>
    );
  }
  if (err.kind === 'other') {
    return (
      <div
        className="flex items-start gap-2 rounded-md border border-red-500/25 bg-red-500/5 p-2.5 text-xs"
        data-testid="apply-wave-error"
      >
        <AlertTriangle className="h-3 w-3 mt-0.5 text-red-500" />
        <div>{String(err.message)}</div>
      </div>
    );
  }
  return null;
}
