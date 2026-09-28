import { uploadUrl } from '../../lib/photo';

/**
 * The hats inside a case, as a tile.
 *
 * Replaces a photo of the case itself, which was the same gray box in every
 * card — every case looks identical from the outside, so the picture carried
 * no information at the moment you were scanning for one. What you are
 * actually looking for is what's in it.
 *
 * The layout follows the count rather than forcing a 2x2: one hat fills the
 * tile, two split it, three or four make a grid. A fixed grid would letterbox
 * a single hat into a quarter of the space for the sake of symmetry.
 */
export function CaseCollage({ thumbs, label }: { thumbs: string[]; label: string }) {
  if (thumbs.length === 0) {
    // A drawn outline, not the word "empty": every place this renders already
    // says so beside it (the tile's "Empty", the case page's "Empty — holds
    // 3"), and the word twice over read as a label that had lost its box.
    return (
      <div className="hr-case-collage-empty">
        <svg viewBox="0 0 64 48" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <rect x="4" y="12" width="56" height="32" rx="6" strokeDasharray="5 4" />
          <path d="M24 12V8a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v4" />
        </svg>
        <span className="visually-hidden">{`${label} is empty`}</span>
      </div>
    );
  }

  return (
    <div
      className="hr-case-collage"
      style={{
        // The static frame (grid, gap, aspect ratio) is in app.css; only the
        // template, which depends on the count, is decided here.
        gridTemplateColumns: thumbs.length === 1 ? '1fr' : '1fr 1fr',
        // Three tiles would otherwise leave a hole; the first spans the top.
        gridTemplateRows: thumbs.length <= 2 ? '1fr' : '1fr 1fr',
      }}
    >
      {thumbs.map((path, i) => (
        <img
          key={path}
          src={uploadUrl(path)}
          alt=""
          loading="lazy"
          // With three hats the first one takes the whole top row, so the
          // grid reads as deliberate rather than as a missing fourth.
          className={thumbs.length === 3 && i === 0 ? 'hr-case-collage-img is-lead' : 'hr-case-collage-img'}
        />
      ))}
      <span className="visually-hidden">{`Hats in ${label}`}</span>
    </div>
  );
}
