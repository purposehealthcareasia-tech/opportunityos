import React from 'react';

const CATEGORY_LABELS = {
  application_updates: 'Application updates',
  interviews:          'Interviews scheduled',
  approvals_expiring:  'Approval expiring reminders',
  receipts:            'New submission receipts',
  support:             'Support ticket replies',
};

const CATEGORY_HINTS = {
  application_updates: 'When an outcome (response / rejection / offer) is logged for one of your applications.',
  interviews:          'When an interview is scheduled or rescheduled on your tracker.',
  approvals_expiring:  'When an authorized submission window has less than 12 hours remaining.',
  receipts:            'When a submission receipt is written for one of your applications.',
  support:             'When a support member replies to one of your tickets.',
};

/**
 * Per-category push preference toggles for <NotificationsSettings/>.
 *
 * Split from `NotificationsSettings.jsx` on 2026-08-11 (P2 Tier-2). All
 * testids preserved verbatim:
 *   notifications-categories · notifications-cat-<key>
 *
 * The label/hint dictionaries moved here alongside their consumer so
 * label churn only touches one file. Zero behaviour change intended.
 */
export function CategoryTogglesList({ prefs, catalog, onToggle }) {
  return (
    <div data-testid="notifications-categories" className="pt-3">
      <p className="text-xs muted mb-2">
        Even if this device is active, categories you turn off will never dispatch.
      </p>
      {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
        <div
          key={key}
          className="flex items-start justify-between gap-4 py-3 border-b border-line dark:border-line-dark last:border-b-0"
        >
          <div className="min-w-0">
            <div className="text-sm font-medium">{label}</div>
            <p className="text-xs muted mt-1">
              {CATEGORY_HINTS[key] || (catalog && catalog[key]) || ''}
            </p>
          </div>
          <label className="inline-flex items-center gap-2 select-none flex-shrink-0">
            <input
              type="checkbox"
              data-testid={`notifications-cat-${key}`}
              checked={!!(prefs && prefs[key])}
              onChange={(e) => onToggle(key, e.target.checked)}
              className="h-4 w-4"
            />
            <span className="text-xs muted">{(prefs && prefs[key]) ? 'on' : 'off'}</span>
          </label>
        </div>
      ))}
    </div>
  );
}
