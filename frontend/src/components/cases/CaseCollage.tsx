/**
 * The hats inside a case, as a tile.
 *
 * Replaces a photo of the case itself, which was the same grey box in every
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
    return (
      <div
        className="d-flex align-items-center justify-content-center text-muted"
        style={{ aspectRatio: '4/3', fontSize: '0.75rem' }}
      >
        empty
      </div>
    );
  }

  return (
    <div
      className="hr-case-collage"
      style={{
        aspectRatio: '4/3',
        display: 'grid',
        gap: 2,
        gridTemplateColumns: thumbs.length === 1 ? '1fr' : '1fr 1fr',
        // Three tiles would otherwise leave a hole; the first spans the top.
        gridTemplateRows: thumbs.length <= 2 ? '1fr' : '1fr 1fr',
      }}
    >
      {thumbs.map((path, i) => (
        <img
          key={path}
          src={`/uploads/${path}`}
          alt=""
          loading="lazy"
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'contain',
            // With three hats the first one takes the whole top row, so the
            // grid reads as deliberate rather than as a missing fourth.
            gridColumn: thumbs.length === 3 && i === 0 ? 'span 2' : undefined,
          }}
        />
      ))}
      <span className="visually-hidden">{`Hats in ${label}`}</span>
    </div>
  );
}
