import { useEffect, useRef, type RefObject } from 'react';

/**
 * Close a picker when the pointer lands anywhere else.
 *
 * Pointerdown rather than click, so the list is gone before a tap on another
 * control lands. The list itself is PORTALLED into `<body>` (see
 * `AnchoredList` — inside the form it is clipped by `.card { overflow:
 * hidden }`), so it is no longer a descendant of the wrapper: without the
 * `.hr-combobox-list` check, pointerdown on an option closes the list before
 * the option's own mousedown can land. Combobox and CasePicker each carried
 * this effect; the second copy is the one that would have lost that check.
 */
export function useClickOutside(
  open: boolean,
  wrapRef: RefObject<HTMLElement | null>,
  onOutside: () => void,
) {
  // Held in a ref so an inline `() => setOpen(false)` doesn't re-subscribe
  // the document listener on every render while the list is open.
  const handler = useRef(onOutside);
  handler.current = onOutside;
  useEffect(() => {
    if (!open) return;
    function onDocDown(e: PointerEvent) {
      const target = e.target as HTMLElement;
      if (wrapRef.current?.contains(target) || target.closest('.hr-combobox-list')) return;
      handler.current();
    }
    document.addEventListener('pointerdown', onDocDown);
    return () => document.removeEventListener('pointerdown', onDocDown);
  }, [open, wrapRef]);
}
