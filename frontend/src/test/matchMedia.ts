/**
 * A `window.matchMedia` stub for jsdom, which implements no CSS engine.
 *
 * Without this, any component asking about the viewport throws on mount. The
 * default answer is "no match" — the mobile-first base case — so installing it
 * changes nothing for the tests that don't care.
 */

let viewportWidth: number | null = null;

const MIN_WIDTH = /\(min-width:\s*([\d.]+)px\)/;
const MAX_WIDTH = /\(max-width:\s*([\d.]+)px\)/;

function matches(query: string): boolean {
  if (viewportWidth === null) return false;
  const min = MIN_WIDTH.exec(query);
  if (min) return viewportWidth >= Number(min[1]);
  const max = MAX_WIDTH.exec(query);
  if (max) return viewportWidth <= Number(max[1]);
  return false;
}

/**
 * Answer media queries as though the window were `px` wide. Reset after every
 * test by the `afterEach` in `test/setup.ts`, so one test's viewport can't
 * leak into the next.
 */
export function setViewportWidth(px: number): void {
  viewportWidth = px;
}

export function installMatchMedia(): void {
  window.matchMedia = ((query: string) => {
    const listeners = new Set<(e: MediaQueryListEvent) => void>();
    return {
      // A getter, not a snapshot: `useSyncExternalStore` re-reads on every
      // render, and a test that sets the width after mount expects the next
      // read to reflect it.
      get matches() {
        return matches(query);
      },
      media: query,
      onchange: null,
      addEventListener: (_: string, l: (e: MediaQueryListEvent) => void) => {
        listeners.add(l);
      },
      removeEventListener: (_: string, l: (e: MediaQueryListEvent) => void) => {
        listeners.delete(l);
      },
      addListener: (l: (e: MediaQueryListEvent) => void) => listeners.add(l),
      removeListener: (l: (e: MediaQueryListEvent) => void) => listeners.delete(l),
      dispatchEvent: () => false,
    } as unknown as MediaQueryList;
  }) as typeof window.matchMedia;
}

export function resetViewportWidth(): void {
  viewportWidth = null;
}
