import { useQuery } from '@tanstack/react-query';
import { getMdnsStatus } from '../../api/settings';
import type { MdnsStatus } from '../../types';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { CopyButton } from '../ui/CopyButton';
import { Skeleton } from '../ui/Skeleton';
import { StatusPill } from '../ui/StatusPill';

export function MdnsCard() {
  // Env-configured — only changes at server boot, so never refetch.
  const mdns = useQuery({
    queryKey: ['settings', 'mdns'],
    queryFn: getMdnsStatus,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const d = mdns.data;

  return (
    <Panel
      title="LAN discovery (mDNS)"
      status={d && mdnsPill(d)}
      description="Read-only — how devices on your network find Headroom by name."
      help={
        <p>
          Configured with the <code>HEADROOM_MDNS_*</code> environment
          variables. Docker needs an overlay for the name to reach your
          network; setup and the Face&nbsp;ID / HTTPS walkthrough are in the
          README (&ldquo;Find it on your LAN&rdquo;).
        </p>
      }
    >
      {mdns.isLoading && <Skeleton lines={3} />}
      <ErrorNote of={mdns} className="mb-0" />
      {d && (
        <div className="hr-metric">
          {/* Three facts, three places. This used to run through `hr-metric`'s
              two slots, which fused the STATE and the IPv4 into one label
              ("Advertising → 10.0.111.4") and left the IPv6 bolted on
              underneath in a different size — two addresses of the same kind
              reading as two unrelated things. The state now lives in the
              header pill, where every settings card keeps its state; the name
              and the addresses stay here. */}
          <div className="hr-mdns-name">
            <div className="hr-net-name">
              {d.url ? (
                <a href={d.url} target="_blank" rel="noopener noreferrer">
                  {d.url}
                </a>
              ) : (
                d.error ?? d.hostname
              )}
            </div>
            {d.url && <CopyButton text={d.url} what="address" />}
          </div>

          {d.advertising && (
            <div className="hr-net-list hr-mdns-list">
              <span className="hr-net-label">IPv4</span>
              <span className="hr-net-value">{d.ip ?? '—'}</span>
              {d.ip ? <CopyButton text={d.ip} what="IPv4 address" /> : <span aria-hidden="true" />}

              {/* Listed even when absent, because the ABSENCE is the
                  diagnosis: with no IPv6 record every lookup of the name
                  stalls for the client's full resolver timeout, which reads
                  as a slow or dead site rather than a missing record. */}
              <span className="hr-net-label">IPv6</span>
              <span className={`hr-net-value${d.ipv6 ? '' : ' is-absent'}`}>
                {d.ipv6 ?? 'none on this host — lookups may be slow'}
              </span>
              {d.ipv6 ? <CopyButton text={d.ipv6} what="IPv6 address" /> : <span aria-hidden="true" />}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

/**
 * The state in one word. "Not advertising" is kept apart from "Off": enabled
 * but silent is a fault to go and look at (the overlay is missing, no LAN
 * address was found), where off is a choice somebody made.
 */
function mdnsPill(d: MdnsStatus) {
  if (d.advertising) return <StatusPill tone="ok">Advertising</StatusPill>;
  if (d.enabled) {
    return (
      <StatusPill tone="warn" title={d.error ?? 'Enabled, but nothing is being advertised'}>
        Not advertising
      </StatusPill>
    );
  }
  return <StatusPill tone="off">Off</StatusPill>;
}

