import { useEffect } from 'react';
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
 * POP is deliberately excluded: that is Back/Forward, where the right behaviour
 * is to return to where you were, not to the top. The browser's own
 * `history.scrollRestoration` handles those, and forcing a scroll would break
 * the far more common "back to the list I was halfway down".
 */
export function ScrollToTop() {
  const { pathname } = useLocation();
  const navigationType = useNavigationType();

  useEffect(() => {
    if (navigationType === 'POP') return;
    window.scrollTo(0, 0);
  }, [pathname, navigationType]);

  return null;
}
