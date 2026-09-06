import { copyText } from '../../lib/clipboard';
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { createShareLink, listShareLinks, revokeShareLink } from '../../api/auth';

/** `''` is the sentinel for "never" — a `<select>` value must be a string. */
const EXPIRY_CHOICES: ReadonlyArray<{ value: string; label: string }> = [
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
  { value: '', label: 'Never' },
];

function expiryNote(expiresAt: string | null | undefined): string {
  // A link with no expiry used to be the only kind this card could make, and
  // it rendered identically to one that expires — so "never" was both the
  // default and invisible. Saying it outright is most of the fix.
  if (!expiresAt) return 'never expires';
  const days = Math.ceil((new Date(expiresAt).getTime() - Date.now()) / 86_400_000);
  if (days <= 0) return 'expired';
  return `expires in ${days} day${days === 1 ? '' : 's'}`;
}

export function ShareLinksCard() {
  const qc = useQueryClient();
  const links = useQuery({ queryKey: ['share-links'], queryFn: listShareLinks });
  const [label, setLabel] = useState('');
  const [expiry, setExpiry] = useState('30');
  const [copied, setCopied] = useState<number | null>(null);

  const createMut = useMutation({
    mutationFn: () => createShareLink(
      label.trim() || 'Shared collection',
      expiry === '' ? null : Number(expiry),
    ),
    onSuccess: () => { setLabel(''); qc.invalidateQueries({ queryKey: ['share-links'] }); },
  });

  // Bare `await revokeShareLink()` in the handler until now — a failed revoke
  // left the link listed as live with no message, which on a link that grants
  // access to the whole collection is the wrong direction to fail silently.
  const revokeMut = useMutation({
    mutationFn: (id: number) => revokeShareLink(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['share-links'] }),
  });

  const active = (links.data ?? []).filter(l => !l.revoked_at);

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Share Links</div>
        <p className="text-secondary small mb-3">
          Read-only links to show off the collection — no login needed to view.
          Revoke any time.
        </p>

        {active.map(l => (
          <div key={l.id} className="d-flex align-items-center gap-2 small mb-2 flex-wrap">
            <span className="fw-semibold">{l.label}</span>
            <span className="text-secondary">{expiryNote(l.expires_at)}</span>
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={async () => {
                // Through `copyText`: a bare `navigator.clipboard.writeText`
                // threw on the plain-HTTP overlay and the button did nothing.
                if (await copyText(`${window.location.origin}${l.url_path}`)) {
                  setCopied(l.id);
                  setTimeout(() => setCopied(null), 1500);
                }
              }}
            >{copied === l.id ? 'Copied!' : 'Copy link'}</button>
            <button
              type="button"
              className="btn btn-link btn-sm p-0"
              style={{ color: 'var(--neon-red)' }}
              onClick={() => {
                if (confirm('Revoke this link? Anyone holding it loses access.')) revokeMut.mutate(l.id);
              }}
              disabled={revokeMut.isPending}
            >revoke</button>
          </div>
        ))}
        {active.length === 0 && <p className="text-muted small">No active share links.</p>}

        <div className="d-flex gap-2 mt-2 flex-wrap align-items-center">
          <input className="form-control" style={{ maxWidth: 260 }} placeholder="Label (e.g. For the group chat)"
            aria-label="Share link label"
            value={label} onChange={e => setLabel(e.target.value)} />
          <select
            className="form-select" style={{ maxWidth: 150 }}
            aria-label="Link expires after"
            value={expiry} onChange={e => setExpiry(e.target.value)}
          >
            {EXPIRY_CHOICES.map(c => (
              <option key={c.label} value={c.value}>{c.label}</option>
            ))}
          </select>
          <button type="button" className="btn btn-primary" onClick={() => createMut.mutate()} disabled={createMut.isPending}>
            Create link
          </button>
        </div>
        {(createMut.error || revokeMut.error) && (
          <div className="alert alert-danger mt-2 mb-0">
            {String(createMut.error ?? revokeMut.error)}
          </div>
        )}
        <p className="text-secondary small mt-2 mb-0">
          A link shows the whole collection, including which room and case each
          hat is in. Anyone it is forwarded to has the same access, so prefer an
          expiry over "Never".
        </p>
      </div>
    </div>
  );
}
