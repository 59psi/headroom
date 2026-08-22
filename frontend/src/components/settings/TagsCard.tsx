import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getTagBase, setTagBase, clearTagBase } from '../../api/settings';

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
  const { data } = useQuery({ queryKey: ['settings', 'tags'], queryFn: getTagBase });
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (v: string) => setTagBase(v),
    onSuccess: () => { setDraft(''); setError(null); qc.invalidateQueries({ queryKey: ['settings', 'tags'] }); },
    onError: (e: Error) => setError(e.message),
  });
  const reset = useMutation({
    mutationFn: clearTagBase,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings', 'tags'] }),
  });

  const pinned = data?.source === 'settings';

  return (
    <div className="card mb-3">
      <div className="card-body">
        <h5 className="card-title">Tags &amp; labels</h5>
        <p className="text-secondary small">
          Print a QR sticker for every hat and case, or write the same URL to an
          NFC tag. Scanning a hat opens a one-tap “wore it today” screen;
          scanning a case opens its contents.
        </p>

        <label className="form-label small" htmlFor="tag-base">Tag host</label>
        <div className="d-flex gap-2 mb-1">
          <input
            id="tag-base"
            aria-label="Tag host"
            className="form-control form-control-sm font-mono"
            placeholder={data?.base_url ?? 'http://headroom.local:8000'}
            value={draft}
            onChange={e => setDraft(e.target.value)}
          />
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={!draft.trim() || save.isPending}
            onClick={() => save.mutate(draft.trim())}
          >Save</button>
          {pinned && (
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={() => reset.mutate()}
              disabled={reset.isPending}
            >Reset</button>
          )}
        </div>
        <p className="text-secondary small">
          {pinned
            ? <>Tags will say <code>{data?.base_url}</code>.</>
            : <>Not set — tags use whatever address you're browsing on
                (<code>{data?.base_url}</code>). Pin
                <code> http://headroom.local:8000</code> so tags keep working
                when the Pi's IP changes.</>}
        </p>
        {error && <p className="text-danger small">{error}</p>}

        <hr />

        <div className="d-flex gap-2 flex-wrap">
          <a
            href="/api/admin/hat-labels"
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-outline-primary btn-sm"
          >🏷 Hat labels</a>
          <a
            href="/api/admin/case-labels"
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-outline-primary btn-sm"
          >🏷 Case labels</a>
        </div>
        <p className="text-secondary small mt-2 mb-0">
          Each label prints its URL as text underneath — that's what you paste
          into a tag writer. Individual hats and cases show a copy button on
          their own page.
        </p>
      </div>
    </div>
  );
}
