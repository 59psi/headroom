import { NavLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getLogo, getRecentErrorsCount } from '../../api/settings';

export function TopNav() {
  const logo = useQuery({ queryKey: ['settings', 'logo'], queryFn: getLogo });
  const errCount = useQuery({
    queryKey: ['admin', 'recent-errors-count'],
    queryFn: getRecentErrorsCount,
    refetchInterval: 60_000,
  });
  const errors = errCount.data?.count ?? 0;

  return (
    <nav className="navbar d-none d-lg-block">
      <div className="container">
        <NavLink to="/" className="navbar-brand">
          {logo.data?.logo_path && (
            <img src={`/uploads/${logo.data.logo_path}`} alt="" />
          )}
          Headroom
        </NavLink>
        <div className="navbar-nav">
          <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} end>Home</NavLink>
          <NavLink to="/cases" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Cases</NavLink>
          <NavLink to="/rooms" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Rooms</NavLink>
          <NavLink to="/hats" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Hats</NavLink>
          <NavLink to="/search" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Search</NavLink>
          <NavLink to="/settings" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} title={errors > 0 ? `Settings (${errors} analysis error${errors === 1 ? '' : 's'})` : 'Settings'} style={{ position: 'relative' }}>
            {errors > 0 && (
              <span style={{
                position: 'absolute', top: 4, right: 4, minWidth: 16, height: 16,
                background: 'var(--neon-red)', color: 'var(--text)',
                borderRadius: '50%', fontSize: '0.55rem', fontWeight: 700,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                padding: '0 4px', boxShadow: '0 0 8px rgba(255,56,96,0.6)',
              }}>{errors > 9 ? '9+' : errors}</span>
            )}
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"/>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
          </NavLink>
        </div>
      </div>
    </nav>
  );
}
