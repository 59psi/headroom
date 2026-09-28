import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { getSharedCollection } from '../api/share';
import { SharedCollectionGrid, SharedCollectionSkeleton } from '../components/share/SharedCollectionGrid';
import { PublicNotice, PublicPage } from '../components/share/PublicPage';


/** Public, read-only collection view — reached via a share-link token. */
export function SharePage() {
  const { token } = useParams<{ token: string }>();
  const { data, isLoading, error } = useQuery({
    queryKey: ['public-share', token],
    queryFn: () => getSharedCollection(token!),
    enabled: !!token,
    retry: false,
  });

  if (isLoading) {
    return (
      <PublicPage>
        <div className="hr-public-head" aria-hidden="true">
          <span className="hr-skeleton hr-public-title-skel" />
        </div>
        <SharedCollectionSkeleton />
      </PublicPage>
    );
  }
  if (error || !data) {
    return (
      <PublicPage>
        <PublicNotice
          title="This link isn't working"
          detail="This share link is invalid, expired, or was revoked."
        />
      </PublicPage>
    );
  }

  return (
    <PublicPage>
      <div className="hr-public-head">
        <h1>{data.label}</h1>
        <p className="hr-public-sub">
          {data.hat_count} hat{data.hat_count !== 1 ? 's' : ''} · shared via Headroom
        </p>
      </div>

      <SharedCollectionGrid hats={data.hats} />
    </PublicPage>
  );
}
