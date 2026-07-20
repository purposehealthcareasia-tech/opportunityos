import React from 'react';
import { NavLink } from 'react-router-dom';
import clsx from 'clsx';
import {
  IdCard,
  Sliders,
  ShieldCheck,
  Rss,
  SendHorizonal,
  ListTodo,
  BarChart3,
  CreditCard,
  Lock,
  Settings as SettingsIcon,
  ShieldAlert,
} from 'lucide-react';

const SECTIONS = [
  { to: '/passport',     label: 'Passport',     Icon: IdCard,          phase: 2, active: false },
  { to: '/preferences',  label: 'Preferences',  Icon: Sliders,         phase: 2, active: false },
  { to: '/eligibility',  label: 'Eligibility',  Icon: ShieldCheck,     phase: 2, active: false },
  { to: '/feed',         label: 'Feed',         Icon: Rss,             phase: 3, active: false },
  { to: '/applications', label: 'Applications', Icon: SendHorizonal,   phase: 4, active: false },
  { to: '/tracker',      label: 'Tracker',      Icon: ListTodo,        phase: 5, active: false },
  { to: '/analytics',    label: 'Analytics',    Icon: BarChart3,       phase: 5, active: false },
  { to: '/billing',      label: 'Billing',      Icon: CreditCard,      phase: 6, active: false },
  { to: '/privacy',      label: 'Privacy',      Icon: Lock,            phase: 2, active: false },
  { to: '/settings',     label: 'Settings',     Icon: SettingsIcon,    phase: 1, active: true  },
];

export function Sidebar({ isAdminOrSupport }) {
  return (
    <aside className="hidden md:flex md:flex-col w-60 border-r border-line dark:border-line-dark bg-white dark:bg-neutral-900">
      <div className="px-5 py-4 border-b border-line dark:border-line-dark">
        <NavLink to="/" className="flex items-center gap-2 text-ink dark:text-ink-dark hover:no-underline">
          <span className="h-6 w-6 rounded-md bg-ink dark:bg-white grid place-items-center">
            <span className="text-white dark:text-ink font-bold text-xs">O</span>
          </span>
          <span className="font-semibold tracking-tight">OpportunityOS</span>
        </NavLink>
      </div>
      <nav className="flex-1 overflow-y-auto py-3 px-2">
        <ul className="space-y-0.5">
          {SECTIONS.map(({ to, label, Icon, active, phase }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  clsx(
                    'group flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-sm no-underline',
                    isActive
                      ? 'bg-neutral-100 dark:bg-neutral-800 text-ink dark:text-ink-dark'
                      : 'text-ink-muted dark:text-ink-dark-muted hover:bg-neutral-50 dark:hover:bg-neutral-800/60 hover:text-ink dark:hover:text-ink-dark',
                  )
                }
              >
                <span className="flex items-center gap-2 min-w-0">
                  <Icon className="h-4 w-4 flex-shrink-0" />
                  <span className="truncate">{label}</span>
                </span>
                {!active && (
                  <span className="text-[10px] uppercase tracking-wide muted flex-shrink-0">P{phase}</span>
                )}
              </NavLink>
            </li>
          ))}
          {isAdminOrSupport && (
            <li className="mt-3 pt-3 border-t border-line dark:border-line-dark">
              <NavLink
                to="/admin"
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm no-underline',
                    isActive
                      ? 'bg-neutral-100 dark:bg-neutral-800 text-ink dark:text-ink-dark'
                      : 'text-ink-muted dark:text-ink-dark-muted hover:bg-neutral-50 dark:hover:bg-neutral-800/60 hover:text-ink dark:hover:text-ink-dark',
                  )
                }
              >
                <ShieldAlert className="h-4 w-4" />
                Admin
              </NavLink>
            </li>
          )}
        </ul>
      </nav>
      <div className="px-4 py-3 border-t border-line dark:border-line-dark text-xs muted">
        Phase 1 · Foundation
      </div>
    </aside>
  );
}
export default Sidebar;
