import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Zap, Loader2 } from 'lucide-react';
import { api } from '../lib/api';

/**
 * DailyBudgetCapsule — sticky bottom capsule showing today's submit
 * progress against the user's plan cap (usage_meters).
 *
 * Honest math: `apps_submitted.used` / `apps_submitted.limit` from
 * `GET /api/v1/usage/me`. If the plan is unlimited (limit=null) the
 * capsule renders "N applied today" with no bar. If the user is at cap,
 * copy says "cap reached — resets in ~Xh" and the CTA disables.
 *
 * One tap of the CTA jumps into `/submit-sprint` — the same route as
 * SmartCTA when a queue exists.
 */
export default function DailyBudgetCapsule() {
  const [state, setState] = useState({ loading: true });

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/usage/me');
      const apps = data?.apps_submitted;
      // apps_submitted is either an int (legacy) or { used, limit, period }.
      const used = typeof apps === 'object' ? (apps?.used ?? 0) : (apps ?? 0);
      const limit = typeof apps === 'object' ? (apps?.limit ?? null) : null;
      setState({
        loading: false,
        used, limit,
        period: (typeof apps === 'object' ? apps?.period : data?.period) || 'today',
      });
    } catch (e) {
      setState({ loading: false, unavailable: true });
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  if (state.loading || state.unavailable) return null;

  const capped = state.limit != null && state.used >= state.limit;
  const pct = state.limit ? Math.min(100, Math.round((state.used / state.limit) * 100)) : null;

  return (
    <div
      className="fixed z-30 bottom-4 left-1/2 -translate-x-1/2 md:left-auto md:translate-x-0 md:right-6 md:bottom-6 pointer-events-none"
      data-testid="daily-budget-capsule-wrap"
    >
      <div className="pointer-events-auto liquid-sheet px-4 py-2.5 flex items-center gap-3 min-w-[280px] max-w-[92vw]">
        <div className="text-xs">
          <div className="font-medium">
            {state.limit != null
              ? <>Applied <span data-testid="dbc-used">{state.used}</span> of <span data-testid="dbc-limit">{state.limit}</span> {state.period}</>
              : <><span data-testid="dbc-used">{state.used}</span> applied {state.period}</>}
          </div>
          {pct != null && (
            <div className="w-40 h-1 rounded-full bg-white/10 mt-1 overflow-hidden">
              <div
                className="h-full bg-accent transition-all duration-300 ease-liquid-ease"
                style={{ width: `${pct}%` }}
                data-testid="dbc-progress"
              />
            </div>
          )}
        </div>
        <Link
          to="/submit-sprint"
          className={`liquid-capsule ${capped ? 'liquid-secondary' : 'liquid-primary'} no-underline text-xs px-3 py-1.5 flex-shrink-0`}
          data-testid="dbc-continue"
          onClick={(e) => { if (capped) e.preventDefault(); }}
          aria-disabled={capped}
          title={capped ? 'Cap reached — resets when the period rolls' : 'Continue your sprint'}
        >
          <Zap className="h-3.5 w-3.5" />
          {capped ? 'Cap reached' : 'Continue sprint'}
        </Link>
      </div>
    </div>
  );
}
