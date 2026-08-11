import React from 'react';
import Button from '../ui/Button';
import { Bell, BellOff } from 'lucide-react';

/**
 * "Push notifications on this device" bar inside <NotificationsSettings/>.
 *
 * Split from `NotificationsSettings.jsx` on 2026-08-11 (P2 Tier-2). All
 * testids preserved verbatim:
 *   notifications-device-state · notifications-test-btn ·
 *   notifications-disable-btn · notifications-enable-btn
 *
 * Zero behaviour change intended.
 */
export function PushDeviceBar({
  hasActiveSubscription,
  permission,
  busy,
  onEnable,
  onDisable,
  onTest,
}) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-line dark:border-line-dark">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4" />
          <span className="text-sm font-medium">Push notifications on this device</span>
          <span
            data-testid="notifications-device-state"
            className={`pill ${hasActiveSubscription ? 'pill-accent' : 'pill-neutral'}`}
          >
            {hasActiveSubscription ? 'active' : 'inactive'}
          </span>
        </div>
        <p className="text-xs muted mt-1">
          Enable on each device you want to receive push on. Permission is asked only when you click Enable.
        </p>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        {hasActiveSubscription ? (
          <>
            <Button
              data-testid="notifications-test-btn"
              variant="secondary"
              size="sm"
              onClick={onTest}
              loading={busy}
            >
              Send test
            </Button>
            <Button
              data-testid="notifications-disable-btn"
              variant="secondary"
              size="sm"
              onClick={onDisable}
              loading={busy}
            >
              <BellOff className="h-3 w-3 mr-1" />
              Disable
            </Button>
          </>
        ) : (
          <Button
            data-testid="notifications-enable-btn"
            variant="accent"
            size="sm"
            onClick={onEnable}
            loading={busy}
            disabled={permission === 'denied'}
          >
            <Bell className="h-3 w-3 mr-1" />
            Enable
          </Button>
        )}
      </div>
    </div>
  );
}
