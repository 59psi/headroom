import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { getGuestHat } from '../api/guest';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

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

  const { data, isLoading, error } = useQuery({
    queryKey: ['guest-hat', id],
    queryFn: () => getGuestHat(id),
    enabled: Number.isFinite(id),
    retry: false,
  });

  if (!Number.isFinite(id) || error) {
    return (
      <div className="text-center py-5 text-secondary" style={{ paddingTop: '20vh' }}>
        <h1>HEADROOM</h1>
        <p>That hat isn't available.</p>
        <Link to="/guest" className="btn btn-outline-primary btn-sm">Back to the collection</Link>
      </div>
    );
  }
  if (isLoading || !data) return <LoadingSpinner />;

  const title = [data.brand, data.model_name].filter(Boolean).join(' ')
    || data.style.replace(/_/g, ' ');

  return (
    <div style={{ maxWidth: 640, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <Link to="/guest" className="btn btn-outline-secondary btn-sm mb-3">← Collection</Link>

      {data.photo_url ? (
        <img
          src={data.photo_url}
          alt=""
          style={{
            width: '100%', maxHeight: 320, objectFit: 'contain',
            filter: 'drop-shadow(0 8px 22px rgba(0,0,0,0.55))',
          }}
        />
      ) : (
        <div style={{ height: 220, display: 'grid', placeItems: 'center', opacity: 0.4, fontSize: '3rem' }}>
          🧢
        </div>
      )}

      <h1 className="mt-3 mb-1">{title}</h1>
      <p className="text-secondary small">
        {data.style.replace(/_/g, ' ')}
        {data.display_id && <> · <span className="font-mono">{data.display_id}</span></>}
      </p>

      {/* The reason a guest opens a hat at all. */}
      <div className="card mb-3">
        <div className="card-body">
          <div className="card-title">Where it lives</div>
          <div className="d-flex gap-4">
            <div>
              <div className="hr-metric-label">Room</div>
              <div className="hr-metric-value">{data.room || '—'}</div>
            </div>
            <div>
              <div className="hr-metric-label">Case</div>
              <div className="hr-metric-value font-mono">{data.case || 'Not in a case'}</div>
            </div>
          </div>
        </div>
      </div>

      {data.colors.length > 0 && (
        <div className="card">
          <div className="card-body">
            <div className="card-title">Colours</div>
            <div className="d-flex flex-wrap gap-2">
              {data.colors.map((c, i) => (
                <span key={i} className="d-flex align-items-center gap-2">
                  <span
                    style={{
                      width: 18, height: 18, borderRadius: '50%',
                      background: c.hex || '#444',
                      border: '1px solid rgba(255,255,255,0.3)',
                      display: 'inline-block',
                    }}
                  />
                  <span className="small text-secondary">{c.name}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
