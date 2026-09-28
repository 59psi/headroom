import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { getSharedCollection } from '../api/share';
import { isNotFound } from '../api/client';
import { SharedCollectionGrid, SharedCollectionSkeleton } from '../components/share/SharedCollectionGrid';
import { PublicNotice, PublicPage } from '../components/share/PublicPage';
import { PublicLoadError } from '../components/share/PublicLoadError';
import { plural } from '../lib/format';
import { qk } from '../lib/queryKeys';

/** Public, read-only collection view — reached via a share-link token. */
export function SharePage() {
  const { token } = useParams<{ token: string }>();
  const shareQ = useQuery({
    queryKey: qk.publicShare(token),
    queryFn: () => getSharedCollection(token!),
    enabled: !!token,
    retry: false,
  });
  const { data, isLoading, error } = shareQ;

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
  // A 404 is the link itself: never issued, expired or revoked. Anything else
  // is the server, and must not tell a good link's holder it was revoked.
  if (error && !isNotFound(error)) {
    return <PublicPage><PublicLoadError query={shareQ} /></PublicPage>;
  }
  if (!data) {
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
          {plural(data.hat_count, 'hat')} · shared via Headroom
        </p>
      </div>

      <SharedCollectionGrid hats={data.hats} />
    </PublicPage>
  );
}
