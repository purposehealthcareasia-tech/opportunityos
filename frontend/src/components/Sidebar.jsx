import React from 'react';
import { NavLink } from 'react-router-dom';
import clsx from 'clsx';
import {
  IdCard,
  Sliders,
  ShieldCheck,
  Rss,
  SendHorizonal,
  ClipboardCheck,
  ListTodo,
  ListChecks,
  Mail,
  BarChart3,
  CreditCard,
  Lock,
  Rocket,
  Settings as SettingsIcon,
  ShieldAlert,
} from 'lucide-react';
import { FyndWordmark } from './FyndMark';

/**
 * Sidebar — Fynd Liquid re-theme.
 * Vertical rail sits on the base wallpaper; each active item is a capsule
 * pill with a specular top-edge (liquid-pill--accent). Inactive items are
 * ghost until hover.
 */

const SECTIONS = [
  { to: '/passport',         label: 'Passport',     Icon: IdCard,          phase: 2, active: true  },
  { to: '/preferences',      label: 'Preferences',  Icon: Sliders,         phase: 2, active: true  },
  { to: '/eligibility',      label: 'Eligibility',  Icon: ShieldCheck,     phase: 2, active: true  },
  { to: '/onboarding/launch',label: 'Launch',       Icon: Rocket,          phase: 6, active: true  },
  { to: '/feed',             label: 'Feed',         Icon: Rss,             phase: 3, active: true  },
  { to: '/applications',     label: 'Applications', Icon: SendHorizonal,   phase: 3, active: true  },
  { to: '/approvals',        label: 'Approvals',    Icon: ClipboardCheck,  phase: 5, active: true  },
  { to: '/tracker',          label: 'Tracker',      Icon: ListTodo,        phase: 5, active: true  },
  { to: '/outcomes',         label: 'Outcomes',     Icon: ListChecks,      phase: 5, active: true  },
  { to: '/follow-ups',       label: 'Follow-ups',   Icon: Mail,            phase: 1, active: true  },
  { to: '/analytics',        label: 'Analytics',    Icon: BarChart3,       phase: 5, active: true  },
  { to: '/billing',          label: 'Billing',      Icon: CreditCard,      phase: 6, active: false },
  { to: '/privacy',          label: 'Privacy',      Icon: Lock,            phase: 2, active: false },
  { to: '/settings',         label: 'Settings',     Icon: SettingsIcon,    phase: 1, active: true  },
];

export function Sidebar({ isAdminOrSupport }) {
  return (
    <aside
      className="hidden md:flex md:flex-col w-64 shrink-0 sticky top-0 h-screen"
      data-testid="sidebar-nav"
    >
      <div className="m-3 mr-0 flex-1 liquid-sheet flex flex-col overflow-hidden">
        <div className="px-5 py-4">
          <NavLink to="/" className="hover:no-underline" data-testid="fynd-home-link">
            <FyndWordmark />
          </NavLink>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 pb-3">
          <ul className="space-y-1">
            {SECTIONS.map(({ to, label, Icon, active, phase }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  data-testid={`sidebar-link-${to.slice(1) || 'home'}`}
                  className={({ isActive }) =>
                    clsx(
                      'group relative flex items-center justify-between gap-2 rounded-full px-3 py-2 text-sm no-underline transition-all duration-200 ease-liquid-ease',
                      isActive
                        ? 'liquid-pill--accent font-medium'
                        : 'text-ink-muted dark:text-ink-dark-muted hover:text-ink dark:hover:text-ink-dark hover:bg-white/40 dark:hover:bg-white/5',
                    )
                  }
                >
                  <span className="flex items-center gap-2.5 min-w-0">
                    <Icon className="h-4 w-4 flex-shrink-0" />
                    <span className="truncate">{label}</span>
                  </span>
                  {!active && (
                    <span className="text-[10px] uppercase tracking-wide opacity-60 flex-shrink-0">P{phase}</span>
                  )}
                </NavLink>
              </li>
            ))}
            {isAdminOrSupport && (
              <li className="mt-3 pt-3 border-t border-white/10">
                <NavLink
                  to="/admin"
                  data-testid="sidebar-link-admin"
                  className={({ isActive }) =>
                    clsx(
                      'flex items-center gap-2.5 rounded-full px-3 py-2 text-sm no-underline transition-all duration-200 ease-liquid-ease',
                      isActive
                        ? 'liquid-pill--accent font-medium'
                        : 'text-ink-muted dark:text-ink-dark-muted hover:text-ink dark:hover:text-ink-dark hover:bg-white/40 dark:hover:bg-white/5',
                    )
                  }
                >
                  <ShieldAlert className="h-4 w-4" /> Admin
                </NavLink>
              </li>
            )}
          </ul>
        </nav>
        <div className="px-5 py-3 border-t border-white/10 dark:border-white/5 text-[11px] muted tracking-wide">
          Fynd · Approve → Submit → Track
        </div>
      </div>
    </aside>
  );
}
export default Sidebar;
