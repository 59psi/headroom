import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { createShareLink, listShareLinks, revokeShareLink } from '../../api/auth';

export function ShareLinksCard() {
  const qc = useQueryClient();
  const links = useQuery({ queryKey: ['share-links'], queryFn: listShareLinks });
  const [label, setLabel] = useState('');
  const [copied, setCopied] = useState<number | null>(null);

  const createMut = useMutation({
    mutationFn: () => createShareLink(label.trim() || 'Shared collection'),
    onSuccess: () => { setLabel(''); qc.invalidateQueries({ queryKey: ['share-links'] }); },
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
            <button
              type="button"
              className="btn btn-outline-secondary btn-sm"
              onClick={async () => {
                await navigator.clipboard.writeText(`${window.location.origin}${l.url_path}`);
                setCopied(l.id);
                setTimeout(() => setCopied(null), 1500);
              }}
            >{copied === l.id ? 'Copied!' : 'Copy link'}</button>
            <button
              type="button"
              className="btn btn-link btn-sm p-0"
              style={{ color: 'var(--neon-red)' }}
              onClick={async () => {
                if (confirm('Revoke this link? Anyone holding it loses access.')) {
                  await revokeShareLink(l.id);
                  qc.invalidateQueries({ queryKey: ['share-links'] });
                }
              }}
            >revoke</button>
          </div>
        ))}
        {active.length === 0 && <p className="text-muted small">No active share links.</p>}

        <div className="d-flex gap-2 mt-2">
          <input className="form-control" style={{ maxWidth: 260 }} placeholder="Label (e.g. For the group chat)"
            value={label} onChange={e => setLabel(e.target.value)} />
          <button type="button" className="btn btn-primary" onClick={() => createMut.mutate()} disabled={createMut.isPending}>
            Create link
          </button>
        </div>
      </div>
    </div>
  );
}
