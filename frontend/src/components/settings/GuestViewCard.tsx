import type { ReactNode } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getGuestView, setGuestView } from '../../api/settings';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Switch } from '../ui/Switch';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';

const QUERY_KEY = ['settings', 'guest-view'] as const;

/**
 * The switch that decides whether the collection is readable without an
 * account.
 *
 * Says plainly what it exposes and what it withholds. "Guest mode" on its own
 * is not enough to decide with — the question anyone actually has is *what
 * will they see*, and the honest answer is short enough to print. So it is
 * printed, as two short lists side by side, rather than folded behind the
 * "How this works" disclosure with the rest of the settings copy: it is the
 * decision itself, not background to it.
 */
export function GuestViewCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const status = useQuery({ queryKey: QUERY_KEY, queryFn: getGuestView });
  const data = status.data;

  // Applies on flip, optimistically: the switch moves the instant it is
  // tapped and the request catches up. The server's answer is predictable
  // (it echoes `{ enabled }` back), so the only way the optimistic state can
  // be wrong is a failed request — and then it snaps back to the value it
  // had, with the reason in the ErrorNote under it. A security switch that
  // stayed ON on screen after the server refused to turn it on would be
  // asserting exposure that is not there (or, the other way, safety).
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => setGuestView(enabled),
    onMutate: async (enabled: boolean) => {
      await qc.cancelQueries({ queryKey: QUERY_KEY });
      const prev = qc.getQueryData<{ enabled: boolean }>(QUERY_KEY);
      qc.setQueryData(QUERY_KEY, { enabled });
      return { prev };
    },
    onError: (_err, _enabled, ctx) => {
      if (ctx?.prev) qc.setQueryData(QUERY_KEY, ctx.prev);
    },
    onSuccess: result => {
      qc.setQueryData(QUERY_KEY, result);
      toast.success(result.enabled ? 'Guest browsing on' : 'Guest browsing off');
    },
    // Not awaited, so the failure note and the rollback show at once rather
    // than after the confirming refetch.
    onSettled: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
      // The login screen's "browse as a guest" link reads this.
      qc.invalidateQueries({ queryKey: ['auth', 'status'] });
    },
  });

  // Unknown is not "off". While the fetch is in flight the body is a
  // skeleton, and when it has failed the switch is disabled with its knob
  // parked mid-track and a pill reading "Unknown": a security setting that
  // reads "Off — sign-in required" because the request 500'd is asserting
  // the opposite of what may be true.
  const known = data !== undefined;
  const enabled = data?.enabled ?? false;

  let pill: ReactNode = null;
  if (known) {
    pill = enabled
      ? <StatusPill tone="info">On</StatusPill>
      : <StatusPill tone="off">Off</StatusPill>;
  } else if (status.isError) {
    pill = <StatusPill tone="error">Unknown</StatusPill>;
  }

  return (
    <Panel
      title="Guest browsing"
      className="hr-sharing"
      status={pill}
      // What the switch DOES, stated whichever way it is set: this used to
      // appear only in the "on" hint, so the reader deciding whether to turn
      // it on was the one reader who never saw it.
      description="Adds a “browse as a guest” link to the login screen, so anyone who can reach Headroom can look through and search the collection."
    >
      {status.isPending ? (
        <Skeleton lines={2} />
      ) : (
        <div className={known ? undefined : 'hr-guest-unknown'}>
          <Switch
            id="guest-view-toggle"
            label="Allow guest browsing"
            hint={!known
              ? 'Unknown — could not load this setting'
              : enabled
                ? 'On — guests can browse without an account.'
                : 'Off — sign-in required.'}
            checked={enabled}
            busy={toggle.isPending}
            disabled={!known}
            // One flip at a time. The switch stays enabled while a save is in
            // flight (it pulses instead of graying out), so a second tap is
            // ignored here rather than racing the first to the server.
            onChange={next => { if (!toggle.isPending) toggle.mutate(next); }}
          />
          {!known && (
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm mt-2"
              onClick={() => status.refetch()}
              disabled={status.isFetching}
            >Try again</button>
          )}
        </div>
      )}
      <ErrorNote of={[status, toggle]} className="mt-2" />

      <div className="hr-guest-scope" role="group" aria-label="What guests see, and what is never sent">
        <div>
          <span className="hr-eyebrow">Guests see</span>
          <ul className="hr-guest-list is-shown">
            <li>Photos</li>
            <li>Brand, model and style</li>
            <li>Colors</li>
            <li>Where each hat lives</li>
          </ul>
        </div>
        <div>
          <span className="hr-eyebrow">Never sent</span>
          <ul className="hr-guest-list is-withheld">
            <li>Prices and values</li>
            <li>What you paid</li>
            <li>What anything sold for</li>
            <li>Your notes</li>
            <li>Hats you've disposed of</li>
          </ul>
        </div>
      </div>
      <p className="text-secondary small mb-0">
        The withheld fields aren't hidden in the page — they're never sent.
        Guests cannot change anything.
      </p>
    </Panel>
  );
}
