import { useState, type FormEvent, type ReactNode } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { caseLabelsUrl, clearTagBase, getTagBase, hatLabelsUrl, setTagBase } from '../../api/settings';
import { qk } from '../../lib/queryKeys';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useToast } from '../ui/Toast';

// Shared with every hat and case page's `TagUrlRow`.
const QUERY_KEY = qk.settings.tags();

/**
 * QR stickers and NFC tags for the physical objects.
 *
 * Both carry one URL and nothing else, so this card configures the host that
 * goes into them and links to the two printable sheets. The NFC half needs no
 * app support beyond the URL: any tag writer (NFC Tools on iOS, NXP TagWriter
 * on Android) writes a URI record, and iOS reads those from the lock screen
 * with no app installed.
 */
export function TagsCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const tags = useQuery({ queryKey: QUERY_KEY, queryFn: getTagBase });
  const data = tags.data;
  const [draft, setDraft] = useState('');

  // The PUT answers with the new status, so the card (and every hat/case
  // page's `TagUrlRow`, which reads the same key) shows the pinned host from
  // the response rather than waiting on a refetch. Errors go through
  // ErrorNote like every other request on this page; this used to keep its
  // own `error` string and render it in a bare red paragraph.
  const save = useMutation({
    mutationFn: (v: string) => setTagBase(v),
    onSuccess: result => {
      setDraft('');
      qc.setQueryData(QUERY_KEY, result);
      toast.success('Tag host saved');
    },
    // Fire-and-forget: returning the promise would keep the button on
    // "Saving…" (and a failure unreported) until the refetch came back.
    onSettled: () => { void qc.invalidateQueries({ queryKey: QUERY_KEY }); },
  });
  const reset = useMutation({
    mutationFn: clearTagBase,
    onSuccess: () => toast.success('Tag host reset'),
    onSettled: () => { void qc.invalidateQueries({ queryKey: QUERY_KEY }); },
  });

  const pinned = data?.source === 'settings';

  function submit(e: FormEvent) {
    e.preventDefault();
    const v = draft.trim();
    if (v && !save.isPending) save.mutate(v);
  }

  let pill: ReactNode = null;
  if (data) {
    pill = pinned
      ? <StatusPill tone="ok">Pinned</StatusPill>
      : <StatusPill tone="off" title="Tags use whatever address you're browsing on">Not pinned</StatusPill>;
  }

  return (
    <Panel
      title="Tags & labels"
      className="hr-sharing"
      status={pill}
      description="Print a QR sticker for every hat and case, or write the same URL to an NFC tag."
      help={
        <>
          <p>
            Scanning a hat opens a one-tap “wore it today” screen; scanning a
            case opens its contents.
          </p>
          <p>
            Each label prints its URL as text underneath — that&rsquo;s what you
            paste into a tag writer. Individual hats and cases show a copy button
            on their own page. Any tag writer that writes a URL record works (NFC
            Tools on iOS, NXP TagWriter on Android), and an iPhone reads the tag
            from the lock screen with no app installed.
          </p>
        </>
      }
      footer={
        <>
          <a
            href={hatLabelsUrl()}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-outline-secondary"
          >Hat labels</a>
          <a
            href={caseLabelsUrl()}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-outline-secondary"
          >Case labels</a>
        </>
      }
    >
      <form onSubmit={submit}>
        <label className="form-label" htmlFor="tag-base">Tag host</label>
        <div className="hr-field-row">
          <input
            id="tag-base"
            aria-label="Tag host"
            className="form-control font-mono hr-share-field"
            placeholder={data?.base_url ?? 'http://headroom.local:8000'}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            inputMode="url"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!draft.trim() || save.isPending}
          >{save.isPending ? 'Saving…' : 'Save'}</button>
          {pinned && (
            <button
              type="button"
              className="btn btn-outline-secondary"
              onClick={() => reset.mutate()}
              disabled={reset.isPending}
            >Reset</button>
          )}
        </div>
      </form>
      {/* No "Not set" while loading: the sentence names the host the tags
          will carry, and before the status arrives it would name nothing. */}
      {!data ? (
        tags.isPending && <Skeleton lines={1} className="mt-2" />
      ) : (
        <p className="text-secondary small mt-2 mb-0 hr-tags-hint">
          {pinned
            ? <>Tags will say <code>{data.base_url}</code>.</>
            : <>Not set — tags use whatever address you're browsing on
                (<code>{data.base_url}</code>). Pin{' '}
                <code>http://headroom.local:8000</code> so tags keep working
                when the Pi's IP changes.</>}
        </p>
      )}
      <ErrorNote of={[tags, save, reset]} className="mt-2" />
    </Panel>
  );
}
