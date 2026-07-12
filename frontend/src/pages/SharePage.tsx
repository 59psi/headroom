import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { apiFetch } from '../api/client';
import { LoadingSpinner } from '../components/common/LoadingSpinner';

interface SharedHat {
  id: number;
  display_id: string | null;
  brand: string | null;
  model_name: string | null;
  style: string;
  photo_url: string | null;
  colors: { name: string; hex: string | null }[];
  case: string | null;
  room: string | null;
}

interface SharedCollection {
  label: string;
  hat_count: number;
  hats: SharedHat[];
}

/** Public, read-only collection view — reached via a share-link token. */
export function SharePage() {
  const { token } = useParams<{ token: string }>();
  const { data, isLoading, error } = useQuery({
    queryKey: ['public-share', token],
    queryFn: () => apiFetch<SharedCollection>(`/api/public/share/${token}`),
    enabled: !!token,
    retry: false,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error || !data) {
    return (
      <div className="text-center py-5 text-secondary" style={{ paddingTop: '20vh' }}>
        <h1>HEADROOM</h1>
        <p>This share link is invalid, expired, or was revoked.</p>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <h1 className="mb-1">{data.label}</h1>
      <p className="text-secondary small mb-4">
        {data.hat_count} hat{data.hat_count !== 1 ? 's' : ''} · shared via Headroom
      </p>

      <div className="row g-3">
        {data.hats.map(hat => (
          <div key={hat.id} className="col-6 col-md-4 col-lg-3">
            <div className="card h-100">
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
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
