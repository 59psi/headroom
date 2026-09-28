/**
 * The shell's own behavior: the activity bar, the skip link, and the two
 * navs' names and states.
 *
 * The activity bar is only worth having if it means something, so most of
 * what is pinned here is what it must NOT light up for — a background
 * refetch (the error badge polls every minute) would otherwise pulse it
 * forever and teach everyone to ignore it.
 */
import { useState } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useMutation, useQuery } from '@tanstack/react-query';
import { renderWithProviders } from '../../test/utils';
import { ActivityBar, AppShell } from './AppShell';
import { BottomNav } from './BottomNav';
import { TopNav } from './TopNav';
import * as settingsApi from '../../api/settings';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getLogo: vi.fn(async () => ({ logo_path: null })),
    getRecentErrorsCount: vi.fn(async () => ({ count: 0 })),
  };
});

const never = () => new Promise<never>(() => {});

function bar() {
  return document.querySelector('.hr-activity')!;
}

beforeEach(() => {
  vi.mocked(settingsApi.getRecentErrorsCount).mockResolvedValue({ count: 0 } as never);
});

describe('ActivityBar', () => {
  it('rests while nothing is loading', () => {
    renderWithProviders(<ActivityBar />);
    expect(bar()).not.toHaveClass('is-active');
  });

  it('lights while a page is waiting on its first load', async () => {
    function Loading() {
      useQuery({ queryKey: ['first-load'], queryFn: never });
      return null;
    }
    renderWithProviders(<><ActivityBar /><Loading /></>);
    await waitFor(() => expect(bar()).toHaveClass('is-active'));
  });

  it('stays dark for a background refetch of data already on screen', async () => {
    const user = userEvent.setup();
    function Refetching() {
      useQuery({ queryKey: ['on-screen'], queryFn: never, staleTime: 0 });
      return null;
    }
    function Gate() {
      const [on, setOn] = useState(false);
      return on ? <Refetching /> : <button type="button" onClick={() => setOn(true)}>Show</button>;
    }
    const { client } = renderWithProviders(<><ActivityBar /><Gate /></>);
    // Data in hand and stale, so mounting a reader refetches it in the
    // background. (Kept from garbage collection: the test client's gcTime is
    // 0, which would drop it before the reader mounts.)
    client.setQueryDefaults(['on-screen'], { gcTime: Infinity });
    client.setQueryData(['on-screen'], { ok: true });

    await user.click(screen.getByRole('button', { name: 'Show' }));

    await waitFor(() => expect(client.isFetching()).toBeGreaterThan(0));
    // Give the bar every chance to (wrongly) react before asserting.
    await act(() => new Promise(r => setTimeout(r, 30)));
    expect(bar()).not.toHaveClass('is-active');
  });

  it('lights while a save is in flight', async () => {
    const user = userEvent.setup();
    function Saver() {
      const m = useMutation({ mutationFn: never });
      return <button type="button" onClick={() => m.mutate()}>Save</button>;
    }
    renderWithProviders(<><ActivityBar /><Saver /></>);
    expect(bar()).not.toHaveClass('is-active');

    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(bar()).toHaveClass('is-active'));
  });

  it('is hidden from assistive tech — pages announce their own loading', () => {
    renderWithProviders(<ActivityBar />);
    expect(bar()).toHaveAttribute('aria-hidden', 'true');
  });
});

describe('skip link', () => {
  it('moves focus to the page without putting #main in the URL', async () => {
    renderWithProviders(<AppShell />);
    const main = document.getElementById('main')!;
    const link = screen.getByRole('link', { name: 'Skip to content' });

    fireEvent.click(link);

    expect(document.activeElement).toBe(main);
    expect(window.location.hash).toBe('');
  });

  it('leaves the page unfocusable again once focus moves on', () => {
    // A permanent tabindex on <main> makes a tap on any blank part of the
    // page steal focus from the field being typed into.
    renderWithProviders(<AppShell />);
    const main = document.getElementById('main')!;
    expect(main).not.toHaveAttribute('tabindex');

    fireEvent.click(screen.getByRole('link', { name: 'Skip to content' }));
    expect(main).toHaveAttribute('tabindex', '-1');

    act(() => main.blur());
    expect(main).not.toHaveAttribute('tabindex');
  });
});

describe('BottomNav', () => {
  it('has the six tabs, each a named link', () => {
    renderWithProviders(<BottomNav />);
    const nav = screen.getByRole('navigation', { name: 'Main' });
    const names = within(nav).getAllByRole('link').map(a => a.textContent);
    expect(names).toEqual(['Home', 'Cases', 'Rooms', 'Hats', 'Search', 'Settings']);
  });

  it('marks the current tab, and only that one', () => {
    renderWithProviders(<BottomNav />, { route: '/hats' });
    const hats = screen.getByRole('link', { name: 'Hats' });
    expect(hats).toHaveClass('active');
    expect(hats).toHaveAttribute('aria-current', 'page');
    // `end` on Home: "/" is a prefix of every path, and without it Home
    // would be lit on every page.
    expect(screen.getByRole('link', { name: 'Home' })).not.toHaveClass('active');
  });

  it('pins the analysis-failure count to Settings', async () => {
    vi.mocked(settingsApi.getRecentErrorsCount).mockResolvedValue({ count: 3 } as never);
    renderWithProviders(<BottomNav />);
    const settings = screen.getByRole('link', { name: /Settings/ });
    expect(await within(settings).findByLabelText('3 hats failed analysis')).toHaveTextContent('3');
  });
});

describe('TopNav', () => {
  it('names the icon-only Settings link, badge or no badge', async () => {
    vi.mocked(settingsApi.getRecentErrorsCount).mockResolvedValue({ count: 2 } as never);
    renderWithProviders(<TopNav />);

    // The tooltip alone left it named by the badge ("2 hats failed
    // analysis") whenever the badge was up.
    const settings = await screen.findByRole('link', { name: /^Settings/ });
    await within(settings).findByLabelText('2 hats failed analysis');
    expect(settings).toHaveAccessibleName(/^Settings/);
  });

  it('lists the five sections as text links', () => {
    renderWithProviders(<TopNav />);
    for (const name of ['Home', 'Cases', 'Rooms', 'Hats', 'Search']) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument();
    }
  });
});
