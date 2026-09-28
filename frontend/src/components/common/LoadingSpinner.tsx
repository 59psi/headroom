/**
 * A page-level "working on it": a neon ring and a word.
 *
 * Both are held back for a moment by the stylesheet (`.hr-loading` fades in
 * after a short delay), so a load the Pi answers in a blink never flashes a
 * spinner at all — the page just appears. The status text is in the DOM from
 * the first frame regardless, so assistive tech hears it immediately.
 *
 * The visible label IS the status message. It used to be printed twice — a
 * visually-hidden copy inside the ring for screen readers and a visible
 * uppercase copy under it — so a screen reader read it out twice.
 */
export function LoadingSpinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="hr-loading" role="status">
      <span className="hr-loading-ring" aria-hidden="true" />
      <span className="hr-loading-label">{label}…</span>
    </div>
  );
}
