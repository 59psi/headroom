import { copyText } from '../../lib/clipboard';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { createShareLink, listShareLinks, revokeShareLink, type ShareLinkInfo } from '../../api/auth';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { StatusPill } from '../ui/StatusPill';
import { Skeleton } from '../ui/Skeleton';
import { useConfirm } from '../ui/Dialogs';
import { useToast } from '../ui/Toast';

const QUERY_KEY = ['share-links'] as const;

/** `''` is the sentinel for "never" — a `<select>` value must be a string. */
const EXPIRY_CHOICES: ReadonlyArray<{ value: string; label: string }> = [
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
  { value: '', label: 'Never' },
];

/** The server's own cap (`ShareLinkCreate.label`). */
const LABEL_MAX = 80;

/** Past its expiry: still listed (it is not revoked), but it opens nothing. */
function isExpired(expiresAt: string | null | undefined): boolean {
  return !!expiresAt && new Date(expiresAt).getTime() <= Date.now();
}

function expiryNote(expiresAt: string | null | undefined): string {
  // A link with no expiry used to be the only kind this card could make, and
  // it rendered identically to one that expires — so "never" was both the
  // default and invisible. Saying it outright is most of the fix.
  if (!expiresAt) return 'never expires';
  const days = Math.ceil((new Date(expiresAt).getTime() - Date.now()) / 86_400_000);
  if (days <= 0) return 'expired';
  return `expires in ${days} day${days === 1 ? '' : 's'}`;
}

function linkUrl(urlPath: string): string {
  return `${window.location.origin}${urlPath}`;
}

export function ShareLinksCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const links = useQuery({ queryKey: QUERY_KEY, queryFn: listShareLinks });
  const [label, setLabel] = useState('');
  const [expiry, setExpiry] = useState('30');
  // The row a create just added, lit briefly so the eye finds it in the list.
  const [fresh, setFresh] = useState<number | null>(null);

  useEffect(() => {
    if (fresh === null) return;
    const t = window.setTimeout(() => setFresh(null), 2400);
    return () => window.clearTimeout(t);
  }, [fresh]);

  async function copy(urlPath: string) {
    // Through `copyText`: a bare `navigator.clipboard.writeText` threw on the
    // plain-HTTP overlay and the button did nothing.
    if (await copyText(linkUrl(urlPath))) toast.success('Link copied');
    else toast.error('Couldn’t copy the link — this browser refused clipboard access.');
  }

  const createMut = useMutation({
    mutationFn: () => createShareLink(
      label.trim() || 'Shared collection',
      expiry === '' ? null : Number(expiry),
    ),
    onSuccess: created => {
      setLabel('');
      setFresh(created.id);
      // Most links are made to be pasted somewhere straight away, so the
      // confirmation carries the copy action rather than sending the person
      // hunting for the new row's button.
      toast.success('Link created', {
        action: { label: 'Copy link', onClick: () => { void copy(created.url_path); } },
      });
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });

  // Bare `await revokeShareLink()` in the handler until one release ago — a
  // failed revoke left the link listed as live with no message, which on a
  // link that grants access to the whole collection is the wrong direction to
  // fail silently.
  //
  // Now optimistic: the row leaves the list the moment the revoke is
  // confirmed, marked revoked in the cache exactly as the server will mark it
  // (the list endpoint keeps revoked links, with `revoked_at` set). A failure
  // puts back THAT row only — not a snapshot of the whole list, which would
  // resurrect a link some other write (a refetch that landed, another device)
  // marked revoked in the meantime — and the reason stays on screen in the
  // ErrorNote.
  //
  // One revoke at a time, still: the Revoke buttons stay disabled while one is
  // in flight. The mutation's `isError` describes only its LATEST `mutate`, so
  // a second revoke started while the first was out made the first one's
  // failure invisible — its row came back with no word said, the exact
  // silent failure the paragraph above is about.
  const revokeMut = useMutation({
    mutationFn: (id: number) => revokeShareLink(id),
    onMutate: async (id: number) => {
      await qc.cancelQueries({ queryKey: QUERY_KEY });
      const before = qc.getQueryData<ShareLinkInfo[]>(QUERY_KEY)?.find(l => l.id === id);
      const now = new Date().toISOString();
      qc.setQueryData<ShareLinkInfo[]>(QUERY_KEY, list =>
        list?.map(l => (l.id === id ? { ...l, revoked_at: now } : l)));
      return { revokedAt: before?.revoked_at ?? null };
    },
    onError: (_err, id, ctx) => {
      qc.setQueryData<ShareLinkInfo[]>(QUERY_KEY, list =>
        list?.map(l => (l.id === id ? { ...l, revoked_at: ctx?.revokedAt ?? null } : l)));
    },
    onSuccess: () => toast.success('Link revoked'),
    // Not returned: a returned promise holds the mutation pending until the
    // refetch lands, which would hold back the ErrorNote on a failure for no
    // reason — the row is already right on screen either way.
    onSettled: () => { void qc.invalidateQueries({ queryKey: QUERY_KEY }); },
  });

  async function revoke(link: ShareLinkInfo) {
    const ok = await confirm({
      title: `Revoke “${link.label}”?`,
      body: 'Anyone holding it loses access.',
      confirmLabel: 'Revoke link',
      tone: 'danger',
    });
    if (ok) revokeMut.mutate(link.id);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!createMut.isPending) createMut.mutate();
  }

  const active = (links.data ?? []).filter(l => !l.revoked_at);
  // The pill counts links that would open right now. An expired link stays
  // in the list (revoking it is still how you tidy it away) but is not access
  // anyone holds, so counting it would overstate what is out there.
  const live = active.filter(l => !isExpired(l.expires_at)).length;

  let pill: ReactNode = null;
  if (links.isSuccess) {
    pill = live > 0
      ? <StatusPill tone="info">{live} active</StatusPill>
      : <StatusPill tone="off">None active</StatusPill>;
  }

  return (
    <Panel
      title="Share links"
      className="hr-sharing"
      status={pill}
      description="Read-only links to show off the collection — no login needed to view. Revoke any time."
      help={
        <p>
          A link shows the whole collection, including which room and case each
          hat is in. Anyone it is forwarded to has the same access, so prefer an
          expiry over “Never”.
        </p>
      }
      footer={
        <form className="hr-share-create" onSubmit={submit}>
          <input
            className="form-control hr-share-create-label"
            placeholder="Label (e.g. For the group chat)"
            aria-label="Share link label"
            maxLength={LABEL_MAX}
            value={label}
            onChange={e => setLabel(e.target.value)}
          />
          <select
            className="form-select"
            aria-label="Link expires after"
            value={expiry}
            onChange={e => setExpiry(e.target.value)}
          >
            {EXPIRY_CHOICES.map(c => (
              <option key={c.label} value={c.value}>{c.label}</option>
            ))}
          </select>
          <button type="submit" className="btn btn-primary hr-share-create-btn" disabled={createMut.isPending}>
            {createMut.isPending ? 'Creating…' : 'Create link'}
          </button>
          {expiry === '' && (
            <p className="hr-share-never small mb-0">
              A link that never expires works until you revoke it — for anyone
              it is forwarded to.
            </p>
          )}
        </form>
      }
    >
      {links.isPending ? (
        <Skeleton lines={2} />
      ) : active.length > 0 && (
        <ul className="hr-share-list">
          {active.map(l => {
            const note = expiryNote(l.expires_at);
            return (
              <li key={l.id} className={`hr-share-row${fresh === l.id ? ' is-fresh' : ''}`}>
                <div className="hr-share-text">
                  <span className="hr-share-label">{l.label}</span>
                  <span
                    className={`hr-share-expiry${!l.expires_at ? ' is-never' : isExpired(l.expires_at) ? ' is-expired' : ''}`}
                  >{note}</span>
                </div>
                <div className="hr-share-actions">
                  <button
                    type="button"
                    className="btn btn-outline-secondary btn-sm"
                    aria-label={`Copy link: ${l.label}`}
                    onClick={() => { void copy(l.url_path); }}
                  >Copy link</button>
                  <button
                    type="button"
                    className="btn btn-outline-danger btn-sm"
                    aria-label={`Revoke link: ${l.label}`}
                    onClick={() => { void revoke(l); }}
                    disabled={revokeMut.isPending}
                  >Revoke</button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {/* Only a SUCCESSFUL empty answer is "no links": a failed fetch used to
          say the same thing while links were live. */}
      {links.isSuccess && active.length === 0 && (
        <p className="text-muted small mb-0">No active share links.</p>
      )}
      <ErrorNote of={links} what="Could not load share links" className="mt-2" />
      <ErrorNote of={[createMut, revokeMut]} className="mt-2" />
    </Panel>
  );
}
