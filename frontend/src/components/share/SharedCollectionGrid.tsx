import { Link } from 'react-router';
import type { SharedHat } from '../../types';
import { CapGlyph } from './PublicPage';

/**
 * The collection as an outside viewer sees it.
 *
 * Shared by the share-link page and the guest view, which show the same thing
 * for different reasons — a secret URL handed to one person, versus anyone who
 * reaches the login screen. The tiles were written for share links and were
 * about to be copied wholesale for guests; two copies of the view that renders
 * a deliberately-narrowed projection is two places for a field to creep back
 * in unnoticed.
 *
 * Renders only what `SharedHat` carries. There are no prices here because
 * there are none in the payload — see the server-side projection.
 */
export function SharedCollectionGrid({ hats, hrefFor }: {
  hats: readonly SharedHat[];
  /** Makes each tile a link. Omitted by the share-link page, which has no
   *  detail route to send anyone to — a tile that looks tappable and isn't is
   *  worse than one that plainly isn't. */
  hrefFor?: (hat: SharedHat) => string;
}) {
  if (!hats.length) {
    return (
      <div className="hr-share-empty">
        <CapGlyph className="hr-share-empty-icon" />
        <p className="mb-0">Nothing to show.</p>
      </div>
    );
  }

  return (
    <div className="row g-3">
      {hats.map(hat => {
        const href = hrefFor?.(hat);
        return (
          <div key={hat.id} className="col-6 col-md-4 col-lg-3">
            {href ? (
              <Link to={href} className="card h-100 text-decoration-none hr-share-tile">
                <Tile hat={hat} />
              </Link>
            ) : (
              <div className="card h-100 hr-share-tile">
                <Tile hat={hat} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Tile-shaped placeholders while the collection loads.
 *
 * The grid is the whole page for an outside viewer, so a centered spinner
 * meant a blank screen that then jumped to a wall of tiles. Placeholders in
 * the grid's own shape hold the layout, and the page settles once.
 *
 * One status message for the lot, not one per tile: eight "Loading…"
 * announcements in a row is noise, not information.
 */
export function SharedCollectionSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="row g-3" role="status">
      <span className="visually-hidden">Loading the collection…</span>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="col-6 col-md-4 col-lg-3" aria-hidden="true">
          <div className="card h-100 hr-share-tile">
            <div className="card-body hr-share-tile-body">
              <span className="hr-skeleton hr-share-thumb" />
              <span className="hr-skeleton hr-skeleton-line hr-share-skel-name" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** The tile body. A separate component rather than a wrapper built inside the
 *  map: defining a component there creates a new type on every render, which
 *  React treats as a different component and remounts. */
function Tile({ hat }: { hat: SharedHat }) {
  return (
    <div className="card-body hr-share-tile-body">
      {hat.photo_url ? (
        <img
          className="hr-share-thumb"
          src={hat.thumb_url ?? hat.photo_url}
          alt=""
          // A collection is a few hundred tiles; only the first screenful
          // should be fetched before the page is usable.
          loading="lazy"
          decoding="async"
        />
      ) : (
        <div className="hr-share-thumb is-empty"><CapGlyph /></div>
      )}
      <div className="hr-share-name">
        {[hat.brand, hat.model_name].filter(Boolean).join(' ') || hat.style_label}
      </div>
      {hat.colors.length > 0 && (
        <div className="hr-share-swatches">
          {hat.colors.slice(0, 3).map((c, i) => (
            <span
              key={i}
              className="hr-share-swatch"
              title={c.name}
              // The color IS the data; everything else about the dot is in
              // the stylesheet.
              style={{ background: c.hex || '#444' }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
