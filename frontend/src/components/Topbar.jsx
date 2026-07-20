import React, { useEffect, useState } from 'react';
import { useAuth } from '../lib/auth';
import { useNavigate } from 'react-router-dom';
import ThemeToggle from './ThemeToggle';
import { LogOut, Gauge } from 'lucide-react';
import { api } from '../lib/api';

function UsageMeterChip() {
  const [usage, setUsage] = useState(null);
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await api.get('/api/v1/usage/me');
        if (alive) setUsage(data);
      } catch (e) { console.debug('usage meter fetch skipped', e); }
    })();
    return () => { alive = false; };
  }, []);
  if (!usage) return null;
  const jp = typeof usage.jobs_processed === 'object' ? (usage.jobs_processed?.used ?? 0) : usage.jobs_processed;
  const ap = typeof usage.applications_prepared === 'object' ? (usage.applications_prepared?.used ?? 0) : usage.apps_prepared;
  const as = typeof usage.apps_submitted === 'object' ? (usage.apps_submitted?.used ?? 0) : usage.apps_submitted;
  const period = usage.period || (usage.jobs_processed?.meter || 'now');
  return (
    <div
      className="hidden md:inline-flex items-center gap-1.5 rounded-md border border-line dark:border-line-dark px-2.5 py-1.5 text-xs muted"
      title={`Period ${period} — jobs scored: ${jp}, apps prepared: ${ap}, apps submitted: ${as}`}
      data-testid="usage-meter-chip"
    >
      <Gauge className="h-3.5 w-3.5" />
      <span className="font-mono">{period}</span>
      <span className="muted">·</span>
      <span data-testid="usage-jobs-processed">{jp} scored</span>
    </div>
  );
}

export function Topbar() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const initials = (user?.name || user?.email || '?').trim().slice(0, 1).toUpperCase();
  return (
    <header className="h-14 border-b border-line dark:border-line-dark bg-white/70 dark:bg-neutral-900/70 backdrop-blur px-4 md:px-6 flex items-center justify-between">
      <div className="text-sm muted">Signed in as <span className="text-ink dark:text-ink-dark font-medium">{user?.email}</span></div>
      <div className="flex items-center gap-2">
        <UsageMeterChip />
        <ThemeToggle />
        <button
          type="button"
          onClick={() => { logout(); nav('/login', { replace: true }); }}
          className="inline-flex items-center gap-2 rounded-md border border-line dark:border-line-dark px-2.5 py-1.5 text-xs muted hover:bg-neutral-100 dark:hover:bg-neutral-800"
        >
          <LogOut className="h-3.5 w-3.5" /> Sign out
        </button>
        <div className="ml-2 h-8 w-8 rounded-full bg-neutral-200 dark:bg-neutral-700 grid place-items-center text-sm font-semibold">{initials}</div>
      </div>
    </header>
  );
}
export default Topbar;
