import { useEffect } from 'react';

/** Body class set while the on-screen keyboard is up. */
export const KEYBOARD_OPEN_CLASS = 'hr-keyboard-open';

// Below this, a viewport shrink is a URL bar collapsing or an address bar
// hiding, not a keyboard. Keyboards take roughly a third of a phone screen;
// browser chrome is well under 150px.
const KEYBOARD_MIN_PX = 150;

/**
 * Track the on-screen keyboard, once, for the whole app.
 *
 * iOS positions `position: fixed` elements against the VISUAL viewport, so
 * when the keyboard opens the fixed bottom nav is lifted with it and lands in
 * the middle of the screen, on top of whatever you were typing into. It is not
 * a z-index problem — the nav is genuinely drawn there — and it happens for
 * every focused input, so an earlier fix that hid the nav only while a custom
 * combobox was open missed plain `<select>`s and text fields entirely.
 *
 * `visualViewport` is the only thing that reports this: no resize event fires
 * on `window` for a keyboard on iOS. Where it is unsupported the class simply
 * never gets set and the nav behaves as it always did, which is correct on a
 * desktop that has no on-screen keyboard.
 */
export function useKeyboardOpen(): void {
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;

    function sync() {
      // `layoutViewport - visualViewport` is the space something is occupying
      // at the bottom — the keyboard, when it's tall enough to be one.
      const occluded = window.innerHeight - (vv!.height + vv!.offsetTop);
      document.body.classList.toggle(KEYBOARD_OPEN_CLASS, occluded > KEYBOARD_MIN_PX);
    }

    sync();
    vv.addEventListener('resize', sync);
    vv.addEventListener('scroll', sync);
    return () => {
      vv.removeEventListener('resize', sync);
      vv.removeEventListener('scroll', sync);
      document.body.classList.remove(KEYBOARD_OPEN_CLASS);
    };
  }, []);
}
