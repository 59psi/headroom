import { useQuery } from '@tanstack/react-query';
import { getMdnsStatus } from '../../api/settings';
import { ErrorNote } from '../common/ErrorNote';

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
        <ErrorNote of={mdns} className="mb-2" />
        {mdns.data && (
          <div className="hr-metric">
            {/* Three facts, three slots. This used to run through `hr-metric`'s
                two, which fused the STATE and the IPv4 into one label
                ("Advertising → 10.0.111.4") and left the IPv6 bolted on
                underneath in a different size — two addresses of the same kind
                reading as two unrelated things. */}
            <div className="hr-net-state">
              <span
                className={`hr-net-dot${mdns.data.advertising ? ' is-live' : ''}`}
                aria-hidden="true"
              />
              {mdns.data.advertising
                ? 'Advertising on your LAN'
                : mdns.data.enabled ? 'Enabled — not advertising' : 'Disabled'}
            </div>

            <div className="hr-net-name">
              {mdns.data.url ? (
                <a href={mdns.data.url} target="_blank" rel="noopener noreferrer">
                  {mdns.data.url}
                </a>
              ) : (
                mdns.data.error ?? mdns.data.hostname
              )}
            </div>

            {mdns.data.advertising && (
              <div className="hr-net-list">
                <span className="hr-net-label">IPv4</span>
                <span className="hr-net-value">{mdns.data.ip ?? '—'}</span>

                {/* Listed even when absent, because the ABSENCE is the
                    diagnosis: with no IPv6 record every lookup of the name
                    stalls for the client's full resolver timeout, which reads
                    as a slow or dead site rather than a missing record. */}
                <span className="hr-net-label">IPv6</span>
                <span className={`hr-net-value${mdns.data.ipv6 ? '' : ' is-absent'}`}>
                  {mdns.data.ipv6 ?? 'none on this host — lookups may be slow'}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
