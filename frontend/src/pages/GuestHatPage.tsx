import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { getGuestHat } from '../api/guest';
import { isNotFound } from '../api/client';
import { CapGlyph, PublicNotice, PublicPage } from '../components/share/PublicPage';
import { PublicLoadError } from '../components/share/PublicLoadError';
import { ImageLightbox } from '../components/common/ImageLightbox';
import { Panel } from '../components/ui/Panel';
import { qk } from '../lib/queryKeys';

/**
 * One hat, as a guest sees it.
 *
 * Renders exactly what `SharedHat` carries and nothing else — there is no
 * price on this page because there is no price in the payload. "Where does
 * this one live" is the question a guest actually has, so case and room are
 * the part given room to breathe.
 */
export function GuestHatPage() {
  const { hatId } = useParams();
  const id = Number(hatId);

  const hatQ = useQuery({
    queryKey: qk.guest.hat(id),
    queryFn: () => getGuestHat(id),
    enabled: Number.isFinite(id),
    retry: false,
  });
  const { data, isLoading, error } = hatQ;

  const back = <Link to="/guest" className="btn btn-outline-secondary btn-sm">← Collection</Link>;

  // "Isn't available" is a 404's answer (the hat is gone, or guest browsing
  // is off). A server failure says so, with a retry, and the way back.
  if (error && !isNotFound(error)) {
    return (
      <PublicPage narrow>
        <div className="hr-public-back">{back}</div>
        <PublicLoadError query={hatQ} />
      </PublicPage>
    );
  }
  if (!Number.isFinite(id) || error) {
    // Spelled out here, not the "← Collection" chip: on this page the link is
    // the only thing to do, and it was always worded as where it goes.
    return (
      <PublicPage narrow>
        <PublicNotice
          title="That hat isn't available"
          action={<Link to="/guest" className="btn btn-primary">Back to the collection</Link>}
        />
      </PublicPage>
    );
  }

  if (isLoading || !data) {
    // The page's own shape — photo, name, the where-it-lives card — rather
    // than a spinner, so arriving from the grid doesn't blank the screen.
    return (
      <PublicPage narrow>
        <div className="hr-public-back">{back}</div>
        <div role="status">
          <span className="visually-hidden">Loading…</span>
          <span className="hr-skeleton hr-public-photo-skel" aria-hidden="true" />
          <span className="hr-skeleton hr-public-title-skel" aria-hidden="true" />
          <span className="hr-skeleton hr-public-card-skel" aria-hidden="true" />
        </div>
      </PublicPage>
    );
  }

  // `style_label` is the server's word for the style ("A-Game") — the same
  // one every owner screen shows; a guest cannot fetch `/api/meta` for it.
  const title = [data.brand, data.model_name].filter(Boolean).join(' ') || data.style_label;

  return (
    <PublicPage narrow>
      <div className="hr-public-back">{back}</div>

      {data.photo_url ? (
        // Tap for full size, like the owner's hat page — a guest looking
        // at a collab mark is exactly who wants to zoom in.
        <div className="hr-public-photo">
          <ImageLightbox src={data.photo_url} alt={title} hat />
        </div>
      ) : (
        <div className="hr-public-photo is-empty"><CapGlyph /></div>
      )}

      <div className="hr-public-head">
        <h1>{title}</h1>
        <p className="hr-public-sub">
          {data.style_label}
          {data.display_id && <> · <span className="font-mono">{data.display_id}</span></>}
        </p>
      </div>

      {/* The reason a guest opens a hat at all. */}
      <Panel title="Where it lives">
        <div className="hr-metric-grid">
          <div className="hr-metric">
            <div className="hr-metric-label">Room</div>
            <div className="hr-metric-value hr-public-place">{data.room || '—'}</div>
          </div>
          <div className="hr-metric">
            <div className="hr-metric-label">Case</div>
            {data.case
              ? <div className="hr-metric-value">{data.case}</div>
              : <div className="hr-metric-value hr-public-place is-none">Not in a case</div>}
          </div>
        </div>
      </Panel>

      {data.colors.length > 0 && (
        <Panel title="Colors">
          <ul className="hr-color-chips">
            {data.colors.map((c, i) => (
              <li key={i} className="hr-color-chip">
                <span className="hr-color-dot" style={{ background: c.hex }} aria-hidden="true" />
                {c.name}
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </PublicPage>
  );
}
