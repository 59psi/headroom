import { NavLink } from 'react-router-dom';

export function TopNav() {
  return (
    <nav className="navbar navbar-expand navbar-dark d-none d-lg-block">
      <div className="container">
        <NavLink to="/" className="navbar-brand fw-bold">Headroom</NavLink>
        <div className="navbar-nav">
          <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} end>Home</NavLink>
          <NavLink to="/cases" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Cases</NavLink>
          <NavLink to="/hats" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Hats</NavLink>
          <NavLink to="/search" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>Search</NavLink>
        </div>
      </div>
    </nav>
  );
}
