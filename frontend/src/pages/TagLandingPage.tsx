import { useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, Link } from 'react-router';
import { getHat, logWear, undoLatestWear } from '../api/hats';
import { invalidateHatViews } from '../lib/invalidate';
import { ErrorNote } from '../components/common/ErrorNote';
import { useToast } from '../components/ui/Toast';
import type { HatRead } from '../types';

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
  const toast = useToast();

  const { data, isLoading, error } = useQuery({
    queryKey: ['hat', id],
    queryFn: () => getHat(id),
    enabled: Number.isFinite(id),
  });

  // Optimistic: the tap flips the page to "Worn today" at once and the
  // request catches up. The server's answer is predictable — today becomes
  // the last-worn date and the count goes up by one (the button only exists
  // when today is not already logged, and the server is idempotent per day
  // regardless) — so the only way the guess can be wrong is a failed
  // request, and then the page snaps back to the button with the reason
  // under it. Waiting on the round trip instead left "Logging…" on screen
  // for as long as the Pi took to answer, which on a phone at the closet
  // door is exactly long enough to wonder whether the tap took.
  const wearMut = useMutation({
    mutationFn: () => logWear(id),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ['hat', id] });
      const prev = qc.getQueryData<HatRead>(['hat', id]);
      if (prev) {
        qc.setQueryData<HatRead>(['hat', id], {
          ...prev,
          date_last_worn: utcToday(),
          wear_count: (prev.wear_count ?? 0) + 1,
        });
      }
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(['hat', id], ctx.prev);
    },
    onSuccess: () => toast.success('Wear logged'),
    // Deliberately NOT returned. A returned promise holds the mutation
    // pending until the refetch lands, and that delays everything waiting on
    // it: a failure's message (by a whole retry, when the server is what
    // failed) and Undo, which only needs the wear itself to have landed.
    onSettled: () => { void invalidateHatViews(qc, id); },
  });
  // Not optimistic: after an undo the last-worn date falls back to whichever
  // wear came before, and only the server knows which that was. The
  // invalidation is returned so "Undoing…" holds until the refetched hat —
  // with the real date — is on screen.
  const undoMut = useMutation({
    mutationFn: () => undoLatestWear(id),
    onSuccess: async () => {
      await invalidateHatViews(qc, id);
      toast.success('Wear undone');
    },
  });

  const wornToday = useMemo(
    () => !!data && data.date_last_worn === utcToday(),
    [data],
  );

  if (!Number.isFinite(id)) return <NotFound detail="That tag doesn't name a hat." />;
  if (isLoading) return <TagSkeleton />;
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
            onClick={() => undoMut.mutate()}
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
          onClick={() => wearMut.mutate()}
          disabled={wearMut.isPending}
        >
          {wearMut.isPending ? 'Logging…' : 'Wore it today'}
        </button>
      )}

      <ErrorNote of={[wearMut, undoMut]} className="hr-tag-note" />

      <p className="hr-tag-meta">
        Worn {data.wear_count ?? 0} time{(data.wear_count ?? 0) === 1 ? '' : 's'}
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
