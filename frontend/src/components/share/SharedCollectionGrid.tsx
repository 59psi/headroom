import { Link } from 'react-router';
import type { SharedHat } from '../../types';

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
    return <p className="text-secondary small">Nothing to show.</p>;
  }

  return (
    <div className="row g-3">
      {hats.map(hat => {
        const href = hrefFor?.(hat);
        return (
          <div key={hat.id} className="col-6 col-md-4 col-lg-3">
            {href ? (
              <Link to={href} className="card h-100 text-decoration-none">
                <Tile hat={hat} />
              </Link>
            ) : (
              <div className="card h-100">
                <Tile hat={hat} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** The tile body. A separate component rather than a wrapper built inside the
 *  map: defining a component there creates a new type on every render, which
 *  React treats as a different component and remounts. */
function Tile({ hat }: { hat: SharedHat }) {
  return (
    <div className="card-body text-center">
      {hat.photo_url ? (
        <img
          src={hat.photo_url}
          alt=""
          style={{ width: '100%', height: 120, objectFit: 'contain' }}
        />
      ) : (
        <div style={{ height: 120, display: 'grid', placeItems: 'center', opacity: 0.4 }}>🧢</div>
      )}
      <div className="small fw-semibold mt-2">
        {[hat.brand, hat.model_name].filter(Boolean).join(' ') || hat.style.replace(/_/g, ' ')}
      </div>
      <div className="d-flex justify-content-center gap-1 mt-1">
        {hat.colors.slice(0, 3).map((c, i) => (
          <span
            key={i}
            title={c.name}
            style={{
              width: 14, height: 14, borderRadius: '50%',
              background: c.hex || '#444',
              border: '1px solid rgba(255,255,255,0.3)',
              display: 'inline-block',
            }}
          />
        ))}
      </div>
    </div>
  );
}
