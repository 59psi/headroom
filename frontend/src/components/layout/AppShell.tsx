import { Suspense } from 'react';
import { Outlet } from 'react-router';
import { useIsFetching, useIsMutating } from '@tanstack/react-query';
import { Skeleton } from '../ui/Skeleton';
import { TopNav } from './TopNav';
import { BottomNav } from './BottomNav';
import { Footer } from './Footer';
import { ScrollToTop } from './ScrollToTop';
import { useKeyboardOpen } from '../../lib/useKeyboardOpen';

export function AppShell() {
  // Once, app-wide: iOS lifts fixed elements with the keyboard, which puts the
  // bottom nav in the middle of the screen over whatever you're typing into.
  useKeyboardOpen();
  return (
    <>
      {/* First in the tab order, visible only on focus: past the seven nav
          links to the page. Handled here rather than left to the `#main`
          fragment, which would put `#main` in the URL and a history entry
          behind it. `main` is focusable only for the moment it takes the
          focus: a permanent tabindex makes a tap on any blank part of the
          page steal focus — and on iOS, close the keyboard. */}
      <a
        className="hr-skip-link"
        href="#main"
        onClick={e => {
          const main = document.getElementById('main');
          if (!main) return;
          e.preventDefault();
          main.setAttribute('tabindex', '-1');
          main.addEventListener('blur', () => main.removeAttribute('tabindex'), { once: true });
          // Focusing scrolls it into view as well.
          main.focus();
        }}
      >
        Skip to content
      </a>
      {/* Installed on iOS, the page runs under a translucent status bar
          (`black-translucent` in index.html), so content scrolled up passed
          beneath the clock and battery. This is a frosted strip exactly the
          height of the status bar — zero everywhere else. */}
      <div className="hr-status-scrim" aria-hidden="true" />
      <ActivityBar />
      <ScrollToTop />
      <TopNav />
      <main id="main" className="container">
        {/* The boundary for the pages `App` loads on demand (Settings, Stats,
            Valuation, bulk import, duplicates): inside `<main>`, so while a
            page's code arrives the nav and footer stay up and only the page
            area holds a placeholder. Above the shell, a first visit to one of
            them blanked the whole app. */}
        <Suspense fallback={<Skeleton lines={4} label="Loading…" />}>
          <Outlet />
        </Suspense>
      </main>
      <Footer />
      <BottomNav />
    </>
  );
}

/**
 * A hairline of light across the top of the screen while the app is waiting
 * on the server: a page's first load, or a save in flight.
 *
 * Every page draws its own loading state in place (a skeleton, a busy
 * button), but those are wherever the content is, and a save a card started
 * is invisible once you have scrolled past it. The bar is the one signal in a
 * fixed place, the way a browser's own progress bar used to be before the
 * app stopped reloading pages.
 *
 * Only FIRST loads count — a query with no data yet, which is to say
 * something on screen is a placeholder. Background refetches are invisible by
 * design and have to stay that way: the analysis-error badge polls every
 * minute and every query refetches on window focus, and a bar that pulses
 * once a minute for nothing teaches the eye to ignore it.
 *
 * The 180 ms before it shows is CSS (a transition delay that applies only on
 * the way in), so a cache hit or a fast LAN answer never flashes it, and
 * there is no timer state here to leak.
 */
export function ActivityBar() {
  const loading = useIsFetching({ predicate: q => q.state.status === 'pending' });
  const saving = useIsMutating();
  const busy = loading + saving > 0;
  return <div className={`hr-activity${busy ? ' is-active' : ''}`} aria-hidden="true" />;
}
