import { useEffect, useRef } from 'react';
import { useLocation, useNavigationType } from 'react-router';

/**
 * Start each new navigation at the top of the page.
 *
 * A browser only resets scroll on a real document load; a client-side route
 * change keeps whatever offset the previous page had. Saving a hat from the
 * bottom of the Add form and tapping through to add another therefore dropped
 * you at the bottom of an empty form, apparently below the end of the page.
 *
 * `<ScrollRestoration />` would do this for us, but it needs a data router and
 * the app mounts a plain `<BrowserRouter>` — so this is the hook version of the
 * same idea.
 *
 * POP is deliberately excluded: that is Back/Forward, where the right behavior
 * is to return to where you were, not to the top. The browser's own
 * `history.scrollRestoration` handles those, and forcing a scroll would break
 * the far more common "back to the list I was halfway down".
 */
export function ScrollToTop() {
  const location = useLocation();
  const navigationType = useNavigationType();
  const lastPath = useRef(location.pathname);

  // Keyed on the whole location (`key` changes on every navigation), then
  // decided here — the dependency list used to be [pathname, navigationType],
  // which fired whenever the TYPE flipped. A page that mirrors its filters
  // into the URL does so with `replace`, so the first filter change (PUSH →
  // REPLACE, same path) scrolled the list back to the top under the thumb
  // that had just changed a filter halfway down it.
  useEffect(() => {
    const samePath = location.pathname === lastPath.current;
    lastPath.current = location.pathname;
    if (navigationType === 'POP') return;
    // REPLACE on the same page is the page updating its own URL (filters, a
    // settings tab), not a new page. A PUSH still scrolls even on the same
    // path: that is a link followed, and it should land at the top.
    if (navigationType === 'REPLACE' && samePath) return;
    window.scrollTo(0, 0);
  }, [location.key, location.pathname, navigationType]);

  return null;
}
