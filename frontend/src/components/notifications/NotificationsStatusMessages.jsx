import React from 'react';
import { CheckCircle2 } from 'lucide-react';

/**
 * Status / error / test-result blocks rendered at the bottom of
 * <NotificationsSettings/>.
 *
 * Split from `NotificationsSettings.jsx` on 2026-08-11 (P2 Tier-2).
 * Testids preserved verbatim:
 *   notifications-status-message · notifications-error-message
 *   notifications-test-summary
 *
 * Zero behaviour change intended.
 */
export function NotificationsStatusMessages({ status, error, testResult }) {
  return (
    <>
      {status && (
        <div
          data-testid="notifications-status-message"
          className="mt-4 text-xs text-accent flex items-center gap-1"
        >
          <CheckCircle2 className="h-3.5 w-3.5" /> {status}
        </div>
      )}
      {error && (
        <div
          data-testid="notifications-error-message"
          className="mt-4 text-xs text-red-600 dark:text-red-400"
        >
          {error}
        </div>
      )}
      {testResult && (
        <div className="mt-2 text-[11px] muted" data-testid="notifications-test-summary">
          Test dispatch: sent {testResult.sent}, failed {testResult.failed}, skipped {testResult.skipped}, pruned {testResult.pruned}
        </div>
      )}
    </>
  );
}
