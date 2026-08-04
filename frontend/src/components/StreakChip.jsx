import React, { useEffect, useMemo, useState } from 'react';
import { Flame } from 'lucide-react';
import { api } from '../lib/api';

/**
 * StreakChip — consecutive-day chip for the Applications page.
 *
 * Honest calculation: count consecutive UTC calendar days on which the
 * user shortlisted or submitted at least one application, ending today.
 * Zero fake urgency; if no streak exists the component renders nothing.
 * Derived on the client from `GET /api/v1/applications` — no new
 * backend surface. Never resets; if the user misses a day the chip
 * simply hides.
 */
export default function StreakChip() {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await api.get('/api/v1/applications');
        if (!alive) return;
        const apps = data?.applications || [];
        const days = new Set();
        for (const a of apps) {
          const ts = a.submitted_at || a.created_at;
          if (!ts) continue;
          days.add(new Date(ts).toISOString().slice(0, 10));
        }
        // Walk backwards from today (UTC) counting consecutive presence.
        let streak = 0;
        for (let i = 0; i < 365; i++) {
          const d = new Date();
          d.setUTCDate(d.getUTCDate() - i);
          const key = d.toISOString().slice(0, 10);
          if (days.has(key)) streak += 1;
          else break;
        }
        setCount(streak);
      } catch (e) {
        if (alive) setCount(0);
      }
    })();
    return () => { alive = false; };
  }, []);

  if (count < 2) return null;
  return (
    <span
      className="liquid-pill liquid-pill--accent text-xs"
      title={`${count} consecutive day${count === 1 ? '' : 's'} of activity`}
      data-testid="streak-chip"
    >
      <Flame className="h-3 w-3" />
      <span data-testid="streak-days">{count}</span>
      <span className="opacity-80">day streak</span>
    </span>
  );
}
