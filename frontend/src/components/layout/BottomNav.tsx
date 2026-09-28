import type { ReactNode } from 'react';
import { NavLink } from 'react-router';
import { AnalysisErrorBadge, useAnalysisErrorCount } from './AnalysisErrorBadge';
import './BottomNav.css';

/** Stroke icons at the tab size; decorative, since each tab's label names it. */
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

// No `end` on Home: React Router special-cases a link to the root route — it
// is active only AT "/", `end` or not — so the prop was dead code, and a
// mutation that removed it changed nothing. The nav test at `/hats` is what
// holds Home unlit on other pages.
const TABS: { to: string; label: string; icon: ReactNode }[] = [
  {
    to: '/', label: 'Home',
    icon: <Icon><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></Icon>,
  },
  {
    to: '/cases', label: 'Cases',
    icon: <Icon><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></Icon>,
  },
  {
    to: '/rooms', label: 'Rooms',
    icon: <Icon><path d="M3 21V8l9-5 9 5v13"/><path d="M9 21V12h6v9"/></Icon>,
  },
  {
    to: '/hats', label: 'Hats',
    icon: <Icon><path d="M12 2C6.5 2 2 6 2 10c0 2 1 4 3 5v3h14v-3c2-1 3-3 3-5 0-4-4.5-8-10-8z"/><path d="M2 15h20"/></Icon>,
  },
  {
    to: '/search', label: 'Search',
    icon: <Icon><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></Icon>,
  },
  {
    to: '/settings', label: 'Settings',
    icon: <Icon><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></Icon>,
  },
];

export function BottomNav() {
  const errors = useAnalysisErrorCount();
  return (
    <nav className="bottom-nav d-lg-none" aria-label="Main">
      {TABS.map(tab => (
        <NavLink
          key={tab.to}
          to={tab.to}
          className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
        >
          {/* The active tab is marked by a lit pill behind its icon, which
              is also what the error count pins to — so the badge sits on the
              icon it belongs to at every width, instead of at a computed
              offset from the tab's center. */}
          <span className="hr-tab-icon">
            {tab.icon}
            {tab.to === '/settings' && <AnalysisErrorBadge count={errors} />}
          </span>
          <span className="hr-tab-label">{tab.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
