import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { apiFetch } from '../api/client';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { SharedCollectionGrid } from '../components/share/SharedCollectionGrid';
import type { SharedCollection } from '../types';


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

      <SharedCollectionGrid hats={data.hats} />
    </div>
  );
}
