import { useQuery } from '@tanstack/react-query';
import { useParams, Link } from 'react-router';
import { getHat } from '../api/hats';
import { isNotFound } from '../api/client';
import { ErrorNote } from '../components/common/ErrorNote';
import { LoadError } from '../components/common/LoadError';
import { localToday } from '../lib/dates';
import { plural } from '../lib/format';
import { useHatLabels } from '../lib/labels';
import { tileSrc } from '../lib/photo';
import { hatName } from '../lib/placement';
import { qk } from '../lib/queryKeys';
import { useWearLog } from '../lib/useWearLog';

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
  const labels = useHatLabels();

  const hatQ = useQuery({
    queryKey: qk.hat(id),
    queryFn: () => getHat(id),
    enabled: Number.isFinite(id),
  });
  const data = hatQ.data;

  // The same wear model as the hat page (`useWearLog`): optimistic — at the
  // closet door a "Logging…" that lasts as long as the Pi takes to answer is
  // exactly long enough to wonder whether the tap took — with a same-day
  // second tap reported as the no-op the server makes it.
  const { wearMut, undoMut } = useWearLog();

  // "Today" is the day on this phone — the day the wear is logged against.
  // The Greenwich date this used to compare with was already tomorrow from
  // 5 pm on the US west coast, which offered a second wear of a hat worn
  // that morning.
  const wornToday = !!data && data.date_last_worn === localToday();

  if (!Number.isFinite(id)) return <NotFound detail="That tag doesn't name a hat." />;
  if (hatQ.isLoading) return <TagSkeleton />;
  // Only a 404 means the hat is gone. A locked database or a dropped
  // connection used to read "no longer in the collection" — telling someone
  // holding the hat that it had been deleted.
  if (hatQ.error && !isNotFound(hatQ.error)) {
    return (
      <div className="hr-tag-landing">
        <h1 className="hr-tag-name">Couldn&rsquo;t load this hat</h1>
        <LoadError what="The tag is fine — the server didn't answer." queries={[hatQ]} />
        <Link to="/hats" className="btn btn-outline-primary">Browse hats</Link>
      </div>
    );
  }
  if (!data) {
    return (
      <NotFound detail="This tag points at a hat that's no longer in the collection." />
    );
  }

  // The model leads here — at the closet door it is what you recognize — and
  // an unidentified hat goes by the name every other screen gives it
  // (`hatName`: its shelf id, else "Hat #12"), not a label of its own.
  const name = data.model_name || hatName(data);
  const sub = [
    data.colorway,
    labels.size(data.size),
    data.display_id !== name && data.display_id,
  ].filter(Boolean).join(' · ');

  return (
    <div className="hr-tag-landing">
      {data.photo_path || data.thumb_path ? (
        <img className="hr-tag-photo" src={tileSrc(data)} alt={name} />
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
        <div className="hr-tag-actions">
          <div className="hr-tag-done" role="status">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
              <path d="M5 12.5l4.5 4.5L19 7.5" />
            </svg>
            Worn today
          </div>
          <button
            type="button"
            className="btn btn-outline-secondary hr-tag-undo"
            onClick={() => undoMut.mutate(id)}
            // Also while the wear itself is still in flight: an undo sent
            // before the log lands would delete the PREVIOUS wear instead.
            disabled={undoMut.isPending || wearMut.isPending}
          >
            {undoMut.isPending ? 'Undoing…' : 'Undo'}
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="btn btn-primary hr-tag-action"
          onClick={() => wearMut.mutate(id)}
          disabled={wearMut.isPending}
        >
          {wearMut.isPending ? 'Logging…' : 'Wore it today'}
        </button>
      )}

      <ErrorNote of={[wearMut, undoMut]} className="hr-tag-note" />

      <p className="hr-tag-meta">
        Worn {plural(data.wear_count ?? 0, 'time')}
        {data.date_last_worn && !wornToday && <> · last {data.date_last_worn}</>}
      </p>

      <Link to={`/hats/${id}`} className="hr-tag-more">Open full hat page →</Link>
    </div>
  );
}

/** The landing's own shape while the hat loads: a tag tap opens this page
 *  cold, and a spinner in the middle of an empty screen is the moment people
 *  decide the tap didn't work. */
function TagSkeleton() {
  return (
    <div className="hr-tag-landing" role="status">
      <span className="visually-hidden">Loading…</span>
      <span className="hr-skeleton hr-tag-photo" aria-hidden="true" />
      <span className="hr-skeleton hr-skeleton-line hr-tag-skel-name" aria-hidden="true" />
      <span className="hr-skeleton hr-tag-skel-action" aria-hidden="true" />
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
