import { useEffect } from 'react';

/** Body class set while any dropdown-style picker is open. */
export const PICKER_OPEN_CLASS = 'hr-picker-open';

// Module-level count, not a boolean: two pickers can be open in sequence and
// the closing one must not clear the class out from under the opening one.
let openPickers = 0;

/**
 * Hide the fixed bottom nav while a picker's list is open.
 *
 * The nav is `position: fixed` at `z-index: 100`, well above the list, so it
 * painted straight over the options. Raising the list's z-index alone is not
 * enough on a phone: when the keyboard opens, iOS positions fixed elements
 * against the visual viewport, so the nav rides up to the middle of the screen
 * and covers the list wherever it is drawn. Taking it out of the layout for
 * the duration removes both problems, and matches what most mobile apps do
 * when the keyboard is up — the nav is not reachable then anyway.
 */
export function usePickerOpen(open: boolean): void {
  useEffect(() => {
    if (!open) return;
    openPickers += 1;
    document.body.classList.add(PICKER_OPEN_CLASS);
    return () => {
      openPickers = Math.max(0, openPickers - 1);
      if (openPickers === 0) {
        document.body.classList.remove(PICKER_OPEN_CLASS);
      }
    };
  }, [open]);
}
