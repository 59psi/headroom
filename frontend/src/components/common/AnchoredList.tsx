import { useState, useLayoutEffect, useCallback } from 'react';
import { portalToBody } from './ModalPortal';

/**
 * A dropdown list rendered into `<body>`, positioned against its input.
 *
 * An absolutely-positioned list inside the form is silently CLIPPED: `.card`
 * sets `overflow: hidden`, so options extending past the card's edge are cut
 * off mid-row and the ones below are unreachable. No amount of z-index fixes
 * that — the pixels are never drawn. `.card-body` also sets
 * `position: relative; z-index: 1`, making each card its own stacking context,
 * and the card hover rule uses `transform`, which creates a containing block
 * that captures `position: fixed` children too. Three separate ancestor traps,
 * all avoided by not being a descendant.
 *
 * The cost of leaving the tree is that the list no longer moves with the
 * input, so its position is measured and re-measured on scroll and resize.
 * That is the trade every portalled dropdown makes.
 */
export function AnchoredList({
  anchor,
  open,
  children,
  ...rest
}: {
  anchor: HTMLElement | null;
  open: boolean;
  children: React.ReactNode;
} & React.HTMLAttributes<HTMLUListElement>) {
  const [box, setBox] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null);

  const measure = useCallback(() => {
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    // Against the VISUAL viewport where available: with the keyboard up, the
    // layout viewport still reports full height, so space measured against it
    // would put the list behind the keyboard.
    const vv = window.visualViewport;
    const viewportH = vv ? vv.height : window.innerHeight;
    const viewportTop = vv ? vv.offsetTop : 0;

    const below = viewportTop + viewportH - r.bottom;
    const above = r.top - viewportTop;
    // Flip up only when below is genuinely cramped AND above is roomier —
    // near the foot of a long form, dropping down leaves the list off-screen.
    const flip = below < 200 && above > below;
    const room = Math.max(120, Math.min((flip ? above : below) - 12, 320));

    setBox({
      // Flipped, the list grows upward from just above the input.
      top: flip ? Math.max(8, r.top - room - 4) : r.bottom + 4,
      left: r.left,
      width: r.width,
      maxHeight: room,
    });
  }, [anchor]);

  useLayoutEffect(() => {
    if (!open) return;
    measure();
    // `true` for capture: a scroll inside any ancestor moves the input, and
    // scroll events from those don't bubble to window.
    window.addEventListener('scroll', measure, true);
    window.addEventListener('resize', measure);
    window.visualViewport?.addEventListener('resize', measure);
    return () => {
      window.removeEventListener('scroll', measure, true);
      window.removeEventListener('resize', measure);
      window.visualViewport?.removeEventListener('resize', measure);
    };
  }, [open, measure]);

  if (!open || !box) return null;

  return portalToBody(
    <ul
      {...rest}
      className={`hr-combobox-list ${rest.className ?? ''}`}
      style={{
        position: 'fixed',
        top: box.top,
        left: box.left,
        width: box.width,
        maxHeight: box.maxHeight,
        ...rest.style,
      }}
    >
      {children}
    </ul>,
  );
}
