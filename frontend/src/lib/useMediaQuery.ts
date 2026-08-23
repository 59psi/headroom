import { useCallback, useSyncExternalStore } from 'react';

/**
 * Subscribe to a CSS media query from React.
 *
 * `useSyncExternalStore` rather than `useState` + an effect: the viewport is
 * an external store, and reading it during render is exactly what this hook
 * is for. The effect version renders one frame at the wrong size before
 * correcting itself, which on the home carousel is a visible pop from one hat
 * to two on every mount.
 *
 * Use this only when the count of rendered elements changes. A purely visual
 * difference belongs in a CSS media query, which costs no JavaScript and
 * cannot disagree with the stylesheet.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      // jsdom ships no CSS engine, so `matchMedia` is absent under test unless
      // something installs it. Answering "no match" degrades to the
      // mobile-first base case, which is the right thing to render when the
      // viewport is unknowable.
      const mql = window.matchMedia?.(query);
      if (!mql) return () => {};
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    },
    [query]
  );

  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia?.(query).matches ?? false,
    () => false
  );
}
