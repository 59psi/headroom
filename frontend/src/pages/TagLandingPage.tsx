import { useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, Link } from 'react-router';
import { getHat, logWear, undoLatestWear } from '../api/hats';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import { invalidateHatViews } from '../lib/invalidate';

/** The server records wears against the UTC date, so "today" must be UTC here
 *  too — a local-midnight comparison would show a hat as unworn for the last
 *  few hours of the day in western timezones, and offer to log a duplicate. */
function utcToday(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Where a hat's QR sticker or NFC tag lands.
 *
 * The entire point of this page is the size of one button. Tags exist so that
 * logging a wear happens at the only moment anyone would actually do it — hat
 * in one hand, phone in the other — and any screen that makes you first find
 * the right control has already lost to not bothering. So: photo to confirm
 * you scanned the right hat, name, one target, done.
 *
 * Deliberately not the full hat page. That page is dense and its wear button
 * sits below several cards; on a phone it is a scroll away from the top.
 */
export function TagLandingPage() {
  const { hatId } = useParams();
  const id = Number(hatId);
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ['hat', id],
    queryFn: () => getHat(id),
    enabled: Number.isFinite(id),
  });

  const wearMut = useMutation({
    mutationFn: () => logWear(id),
    onSuccess: () => invalidateHatViews(qc, id),
  });
  const undoMut = useMutation({
    mutationFn: () => undoLatestWear(id),
    onSuccess: () => invalidateHatViews(qc, id),
  });

  const wornToday = useMemo(
    () => !!data && data.date_last_worn === utcToday(),
    [data],
  );

  if (!Number.isFinite(id)) return <NotFound detail="That tag doesn't name a hat." />;
  if (isLoading) return <LoadingSpinner />;
  if (error || !data) {
    return (
      <NotFound detail="This tag points at a hat that's no longer in the collection." />
    );
  }

  const name = data.model_name || 'Unidentified hat';
  const sub = [data.colorway, data.size, data.display_id].filter(Boolean).join(' · ');
  const photo = data.thumb_path || data.photo_path;

  return (
    <div className="hr-tag-landing">
      {photo ? (
        <img className="hr-tag-photo" src={`/uploads/${photo}`} alt={name} />
      ) : (
        <div className="hr-tag-photo hr-tag-photo-empty">No photo</div>
      )}

      <h1 className="hr-tag-name">{name}</h1>
      {sub && <p className="hr-tag-sub">{sub}</p>}

      {data.disposed_at ? (
        <p className="hr-tag-note">
          This hat has left the collection, so wears can't be logged against it.
        </p>
      ) : wornToday ? (
        <>
          <div className="hr-tag-done" role="status">✓ Worn today</div>
          <button
            type="button"
            className="btn btn-outline-secondary"
            onClick={() => undoMut.mutate()}
            disabled={undoMut.isPending}
          >
            {undoMut.isPending ? 'Undoing…' : 'Undo'}
          </button>
        </>
      ) : (
        <button
          type="button"
          className="btn btn-primary hr-tag-action"
          onClick={() => wearMut.mutate()}
          disabled={wearMut.isPending}
        >
          {wearMut.isPending ? 'Logging…' : 'Wore it today'}
        </button>
      )}

      {wearMut.isError && (
        <p className="hr-tag-note text-danger">
          {(wearMut.error as Error).message}
        </p>
      )}

      <p className="hr-tag-meta">
        Worn {data.wear_count ?? 0} time{(data.wear_count ?? 0) === 1 ? '' : 's'}
        {data.date_last_worn && !wornToday && <> · last {data.date_last_worn}</>}
      </p>

      <Link to={`/hats/${id}`} className="hr-tag-more">Open full hat page →</Link>
    </div>
  );
}

function NotFound({ detail }: { detail: string }) {
  return (
    <div className="hr-tag-landing">
      <h1 className="hr-tag-name">Tag not recognized</h1>
      <p className="hr-tag-sub">{detail}</p>
      <Link to="/hats" className="btn btn-outline-primary">Browse hats</Link>
    </div>
  );
}
