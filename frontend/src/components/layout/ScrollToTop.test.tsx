import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useNavigate } from 'react-router';
import { ScrollToTop } from './ScrollToTop';
import { AppShell } from './AppShell';
import { renderWithProviders } from '../../test/utils';

/**
 * `useNavigationType` is mocked rather than driven through real history, so a
 * POP can be asserted without depending on how MemoryRouter reports Back.
 */
const nav = vi.hoisted(() => ({ type: 'PUSH' as 'PUSH' | 'POP' | 'REPLACE' }));

vi.mock('react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router')>()),
  useNavigationType: () => nav.type,
}));

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getLogo: vi.fn(async () => ({ logo_path: null })),
    getRecentErrorsCount: vi.fn(async () => ({ count: 0 })),
  };
});

describe('ScrollToTop', () => {
  let scrollTo: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    nav.type = 'PUSH';
  });
  afterEach(() => scrollTo.mockRestore());

  function renderAt(path: string) {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <ScrollToTop />
      </MemoryRouter>,
    );
  }

  it('scrolls to the top on a pushed navigation', () => {
    renderAt('/hats/new');
    expect(scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it('leaves the scroll position alone on Back/Forward', () => {
    nav.type = 'POP';
    renderAt('/hats');
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it('scrolls again when the path changes', async () => {
    const user = userEvent.setup();

    function GoToAddHat() {
      const navigate = useNavigate();
      return <button onClick={() => navigate('/hats/new')}>go</button>;
    }

    render(
      <MemoryRouter initialEntries={['/hats']}>
        <ScrollToTop />
        <GoToAddHat />
      </MemoryRouter>,
    );
    expect(scrollTo).toHaveBeenCalledTimes(1);

    // The reported case: leaving one page for another must re-fire the scroll,
    // not just run once on mount.
    await user.click(screen.getByText('go'));
    expect(scrollTo).toHaveBeenCalledTimes(2);
  });

  it('is actually mounted by the app shell', () => {
    // Writing the component and forgetting to mount it would leave every test
    // above green while nothing scrolled in the real app.
    renderWithProviders(<AppShell />);
    expect(scrollTo).toHaveBeenCalledWith(0, 0);
  });
});
