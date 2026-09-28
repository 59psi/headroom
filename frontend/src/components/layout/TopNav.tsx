import { NavLink } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { getLogo } from '../../api/settings';
import { logoSrc } from '../../lib/photo';
import { AnalysisErrorBadge, analysisErrorLabel, useAnalysisErrorCount } from './AnalysisErrorBadge';

/** The desktop tabs, in the bottom nav's order. Settings is the gear after them. */
const LINKS: { to: string; label: string; end?: boolean }[] = [
  { to: '/', label: 'Home', end: true },
  { to: '/cases', label: 'Cases' },
  { to: '/rooms', label: 'Rooms' },
  { to: '/hats', label: 'Hats' },
  { to: '/search', label: 'Search' },
];

const linkClass = ({ isActive }: { isActive: boolean }) => `nav-link${isActive ? ' active' : ''}`;

export function TopNav() {
  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });
  const errors = useAnalysisErrorCount();

  return (
    <nav className="navbar d-none d-lg-block" aria-label="Main">
      <div className="container">
        <NavLink to="/" className="navbar-brand">
          {logoSrc(logo.data) && (
            <img src={logoSrc(logo.data)!} alt="" />
          )}
          Headroom
        </NavLink>
        <div className="navbar-nav">
          {LINKS.map(link => (
            <NavLink key={link.to} to={link.to} end={link.end} className={linkClass}>
              {link.label}
            </NavLink>
          ))}
          {/* Icon-only, so its name is spelled out for a screen reader — the
              tooltip alone left it named by the badge ("3 hats failed
              analysis") whenever the badge was up, with "Settings" gone. */}
          <NavLink
            to="/settings"
            className={({ isActive }) => `nav-link hr-nav-icon${isActive ? ' active' : ''}`}
            title={errors > 0 ? `Settings (${analysisErrorLabel(errors)})` : 'Settings'}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            <span className="visually-hidden">Settings</span>
            {/* Placed by the stylesheet (`.navbar .hr-nav-error-badge`). */}
            <AnalysisErrorBadge count={errors} />
          </NavLink>
        </div>
      </div>
    </nav>
  );
}
