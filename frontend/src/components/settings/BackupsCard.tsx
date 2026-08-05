import { useQuery } from '@tanstack/react-query';
import { listBackups, backupDownloadUrl } from '../../api/settings';

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function BackupsCard() {
  const backups = useQuery({ queryKey: ['admin', 'backups'], queryFn: listBackups });

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">Backups</div>
        <p className="text-secondary small mb-3">
          Backups are gzipped tarballs of <code>/data</code>. Scheduled rolling
          backups run inside the container and are kept under <code>/data/backups/</code>.
          Use <strong>DB only</strong> when the photo tree is large and you only
          need the metadata captured (photos are JPEG/PNG so they barely compress
          anyway).
        </p>
        <div className="d-flex gap-2 mb-2 flex-wrap">
          <a href={backupDownloadUrl(true)} className="btn btn-primary" download>
            ↓ Full Backup
          </a>
          <a href={backupDownloadUrl(false)} className="btn btn-outline-primary" download>
            ↓ DB Only
          </a>
        </div>
        <p className="text-muted small mb-3" style={{ fontSize: '0.75rem' }}>
          <strong>Full</strong> = SQLite DB + every uploaded photo (hats, cases, branding).
          Restore by dropping the extracted <code>data/</code> back into <code>/data/</code>.
          <br/>
          <strong>DB only</strong> = just <code>headroom.db</code>. All hat metadata, cases,
          colors, prices — but no photos. Faster to download.
        </p>
        {backups.data && backups.data.length > 0 && (
          <div>
            <div className="hr-tier-label mb-2">Scheduled snapshots ({backups.data.length})</div>
            {backups.data.slice(0, 7).map(b => (
              <div key={b.filename} className="hr-color-row" style={{ paddingTop: '0.5rem' }}>
                <div className="flex-grow-1 font-mono small" style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {b.filename}
                </div>
                <div className="text-muted small font-mono">{formatBytes(b.size_bytes)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
