import { useQuery } from '@tanstack/react-query';
import { getMdnsStatus } from '../../api/settings';

export function MdnsCard() {
  // Env-configured — only changes at server boot, so never refetch.
  const mdns = useQuery({
    queryKey: ['settings', 'mdns'],
    queryFn: getMdnsStatus,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  return (
    <div className="card mb-3">
      <div className="card-body">
        <div className="card-title">LAN Discovery (mDNS)</div>
        <p className="text-secondary small mb-3">
          Read-only — configured with the <code>HEADROOM_MDNS_*</code> environment
          variables. Docker needs an overlay for the name to reach your network;
          setup and the Face&nbsp;ID / HTTPS walkthrough are in the README
          ("Find it on your LAN").
        </p>
        {mdns.data && (
          <div className="hr-metric">
            <div className="hr-metric-label">
              {mdns.data.advertising
                ? `Advertising → ${mdns.data.ip}`
                : mdns.data.enabled ? 'Enabled — not advertising' : 'Disabled'}
            </div>
            <div className="hr-metric-value font-mono">
              {mdns.data.url ? (
                <a href={mdns.data.url} target="_blank" rel="noopener noreferrer">
                  {mdns.data.url}
                </a>
              ) : (
                mdns.data.error ?? mdns.data.hostname
              )}
            </div>
            {/* Shown because its ABSENCE is the diagnosis: without an IPv6
                record every lookup of the name stalls for the client's full
                resolver timeout, which reads as a slow or dead site. */}
            {mdns.data.advertising && (
              <div className="text-secondary small font-mono hr-mdns-v6">
                {mdns.data.ipv6
                  ? `IPv6 → ${mdns.data.ipv6}`
                  : 'IPv6 → none on this host (lookups may be slow)'}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
