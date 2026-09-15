import React, { useEffect, useState } from 'react';
import { useAuth } from '../lib/auth';
import { Link, useNavigate } from 'react-router-dom';
import ThemeToggle from './ThemeToggle';
import { LogOut, Gauge } from 'lucide-react';
import { api } from '../lib/api';
import SmartCTA from './SmartCTA';

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
      className="liquid-pill hidden md:inline-flex text-xs"
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
    <header
      className="liquid-bar sticky top-0 z-40 h-14 px-4 md:px-6 flex items-center justify-between"
      data-testid="topbar"
    >
      <div className="text-sm muted truncate">Signed in as <span className="text-ink dark:text-ink-dark font-medium">{user?.email}</span></div>
      <div className="flex items-center gap-2">
        <SmartCTA className="hidden lg:inline-flex text-xs" />
        <UsageMeterChip />
        <Link to="/research" className="md:hidden liquid-capsule liquid-secondary text-xs" data-testid="mobile-research-link">Research</Link>
        <ThemeToggle />
        <button
          type="button"
          onClick={() => { logout(); nav('/login', { replace: true }); }}
          className="liquid-capsule liquid-secondary text-xs"
          data-testid="topbar-signout"
        >
          <LogOut className="h-3.5 w-3.5" /> Sign out
        </button>
        <div className="ml-2 h-8 w-8 rounded-full bg-gradient-to-br from-accent to-accent-hover text-white grid place-items-center text-sm font-semibold shadow-liquid-1-light dark:shadow-liquid-1">{initials}</div>
      </div>
    </header>
  );
}
export default Topbar;
