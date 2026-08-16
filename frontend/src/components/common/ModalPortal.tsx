import { createPortal } from 'react-dom';

/**
 * Render modal chrome into `document.body` instead of where it sits in the tree.
 *
 * `.modal` is `position: fixed; z-index: 1050`, which reads like it can never be
 * covered — but z-index only ranks siblings *within a stacking context*, and
 * `.card-body` sets `position: relative; z-index: 1`, making every card on the
 * page its own context. A modal rendered inside one is confined to that card's
 * slot in the page's stacking order, so any later sibling card paints over it.
 * That is exactly how the photo cropper's zoom slider and "Use This" button
 * ended up underneath the Details card's style/size/condition selects: the
 * cropper lives inside the Photo card, which comes first.
 *
 * Portalling to `<body>` lifts the modal out of every card's context, so its
 * z-index is finally measured against the page. It also immunises modals
 * against the other two ancestor traps that silently clip `position: fixed`
 * children — `overflow: hidden`, and any `transform`/`filter`, which create a
 * containing block. The card hover rule uses `transform: translateY(-2px)`, so
 * that second trap is one hover away from being real too.
 *
 * Written as a call rather than a wrapper component so adopting it is a
 * one-line change at each `return (` and the JSX below keeps its indentation.
 */
export function portalToBody(node: React.ReactNode) {
  return createPortal(node, document.body);
}
