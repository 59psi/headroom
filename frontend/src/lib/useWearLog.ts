import { useMutation, useQueryClient } from '@tanstack/react-query';
import { logWear, undoLatestWear } from '../api/hats';
import { useToast } from '../components/ui/Toast';
import { invalidateHatViews } from './invalidate';
import { localToday } from './dates';
import { qk } from './queryKeys';
import type { HatRead } from '../types';

/**
 * Logging a wear, and taking one back — one model of the server's contract
 * for both places a wear is logged: the hat page and the tag landing page.
 *
 * They were two implementations of the same two routes and had drifted: the
 * hat page waited for the server, spotted a same-day no-op by comparing
 * counts and offered an Undo; the tag page was optimistic, judged "worn
 * today" against the date in Greenwich, never offered the Undo, and awaited
 * one refetch but not the other. What the server does is one thing, so it is
 * modeled once:
 *
 * - **Optimistic.** The answer is predictable — today becomes the last-worn
 *   date and the count goes up by one — unless today is already logged, when
 *   the server treats the tap as a no-op and so does the guess. A failure
 *   puts the snapshot back and the page says why.
 * - **Idempotency, from the server's answer.** The count before the tap is
 *   compared with the count the server returns, so a second tap the same day
 *   says so — and offers no Undo, since undoing a no-op would delete the
 *   earlier, real wear.
 * - **An Undo that only undoes this wear.** The server's undo is "delete the
 *   LATEST wear", so the toast's Undo acts only while the count is still the
 *   one this wear produced; once the inline Undo has taken it back, the
 *   toast's would delete an earlier one.
 *
 * Both mutations take the hat as their VARIABLE rather than closing over an
 * id: the toast lives at the app root and outlives the page, and React
 * Router keeps a detail page mounted from one hat to the next, where TanStack
 * hands a mutation the latest render's options. A closure undid a wear on
 * whichever hat was on screen when the toast was tapped.
 *
 * Both routes answer with the hat as it now stands, which goes straight into
 * the cache. `row` is optional only because a test double may answer nothing.
 */
export function useWearLog() {
  const qc = useQueryClient();
  const toast = useToast();

  const undoMut = useMutation({
    mutationFn: (hatId: number) => undoLatestWear(hatId),
    // Not optimistic: after an undo the last-worn date falls back to whichever
    // wear came before, and only the server knows which that was. Its answer
    // carries it, so the row goes in as soon as it arrives.
    onSuccess: (row: HatRead | undefined, hatId) => {
      if (row) qc.setQueryData(qk.hat(hatId), row);
      toast.success('Last wear removed');
    },
    onSettled: (_res, _err, hatId) => { void invalidateHatViews(qc, hatId); },
  });

  const wearMut = useMutation({
    mutationFn: (hatId: number) => logWear(hatId),
    onMutate: async (hatId: number) => {
      // A poll landing mid-flight would repaint the pre-tap row over the guess.
      await qc.cancelQueries({ queryKey: qk.hat(hatId) });
      const prev = qc.getQueryData<HatRead>(qk.hat(hatId));
      const today = localToday();
      if (prev && prev.date_last_worn !== today) {
        qc.setQueryData<HatRead>(qk.hat(hatId), {
          ...prev,
          date_last_worn: today,
          wear_count: (prev.wear_count ?? 0) + 1,
        });
      }
      return { prev };
    },
    onError: (_err, hatId, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.hat(hatId), ctx.prev);
    },
    onSuccess: (row: HatRead | undefined, hatId, ctx) => {
      if (row) qc.setQueryData(qk.hat(hatId), row);
      // Measured against the row as it was BEFORE the tap — the cache now
      // holds the optimistic guess, which always looks like a new wear.
      const before = ctx?.prev?.wear_count;
      const after = row?.wear_count;
      if (before != null && after != null && after === before) {
        toast.info('Already logged for today');
        return;
      }
      toast.success('Wear logged', {
        action: {
          label: 'Undo',
          // Either count unknown — the page's cache already dropped, or the
          // server's answer never arrived in a test double — still undoes:
          // there is nothing to check against.
          onClick: () => {
            const now = qc.getQueryData<HatRead>(qk.hat(hatId))?.wear_count;
            if (after === undefined || now === undefined || now === after) undoMut.mutate(hatId);
          },
        },
      });
    },
    // Deliberately NOT returned. A returned promise holds the mutation
    // pending until every list has refetched, which delays a failure's
    // message (by a whole retry, when the server is what failed) and the
    // Undo, which only needs the wear itself to have landed.
    onSettled: (_res, _err, hatId) => { void invalidateHatViews(qc, hatId); },
  });

  return { wearMut, undoMut };
}
