/**
 * Routing primitives the app's route table depends on.
 *
 * Added with the react-router v7 -> v8 upgrade. v8's breaking changes are
 * concentrated in framework mode (loaders, middleware, RSC, `meta`), none of
 * which this app uses — it is declarative mode only. This pins the behaviour
 * it *does* rely on so "the breaking changes don't apply to us" is a checked
 * claim rather than an assumption.
 *
 * Covers the symbols App.tsx and the layout use: Routes/Route, nested layout
 * routes via Outlet, NavLink active state, useParams, useNavigate and
 * useSearchParams. (Link and MemoryRouter are already exercised end-to-end by
 * the component tests.)
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  MemoryRouter, Routes, Route, Outlet, NavLink,
  useParams, useNavigate, useSearchParams,
} from 'react-router';

function Shell() {
  return (
    <div>
      <nav>
        <NavLink to="/hats" className={({ isActive }) => (isActive ? 'active' : 'idle')}>
          Hats
        </NavLink>
      </nav>
      <main><Outlet /></main>
    </div>
  );
}

function HatDetail() {
  const { hatId } = useParams<{ hatId: string }>();
  return <div>hat {hatId}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<div>login page</div>} />
        <Route element={<Shell />}>
          <Route path="/" element={<div>home</div>} />
          <Route path="/hats" element={<div>hats list</div>} />
          <Route path="/hats/new" element={<div>add hat</div>} />
          <Route path="/hats/:hatId" element={<HatDetail />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('route matching', () => {
  it('renders a pathless layout route around its children', () => {
    renderAt('/hats');
    expect(screen.getByText('hats list')).toBeInTheDocument();
    expect(screen.getByRole('navigation')).toBeInTheDocument(); // Outlet host
  });

  it('keeps public routes outside the layout', () => {
    // /login and /share/:token deliberately sit outside <Route element={<AppShell/>}>.
    renderAt('/login');
    expect(screen.getByText('login page')).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it('prefers the static segment over the dynamic one', () => {
    // /hats/new and /hats/:hatId overlap; if precedence flipped, "new" would
    // render the detail page with hatId="new".
    renderAt('/hats/new');
    expect(screen.getByText('add hat')).toBeInTheDocument();
  });

  it('passes URL params through useParams', () => {
    renderAt('/hats/42');
    expect(screen.getByText('hat 42')).toBeInTheDocument();
  });
});

describe('NavLink active state', () => {
  it('marks the matching link active and others idle', () => {
    renderAt('/hats');
    expect(screen.getByRole('link', { name: 'Hats' })).toHaveClass('active');
  });

  it('is idle on a non-matching route', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: 'Hats' })).toHaveClass('idle');
  });
});

describe('navigation hooks', () => {
  it('useNavigate moves to another route', async () => {
    const user = userEvent.setup();
    function GoHome() {
      const navigate = useNavigate();
      return <button onClick={() => navigate('/hats/7')}>go</button>;
    }
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<GoHome />} />
          <Route path="/hats/:hatId" element={<HatDetail />} />
        </Routes>
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: 'go' }));
    expect(screen.getByText('hat 7')).toBeInTheDocument();
  });

  it('useSearchParams reads the query string', () => {
    // AddHatPage seeds its case select from ?caseId=…
    function ReadParam() {
      const [params] = useSearchParams();
      return <div>caseId={params.get('caseId') ?? 'none'}</div>;
    }
    render(
      <MemoryRouter initialEntries={['/hats/new?caseId=4']}>
        <Routes><Route path="/hats/new" element={<ReadParam />} /></Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('caseId=4')).toBeInTheDocument();
  });
});
