import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';

/**
 * Install Caddy's root CA on the device you're reading this on.
 *
 * `https://headroom.local` is signed by Caddy's own CA, because Let's Encrypt
 * cannot issue for `.local`. Until a device trusts that CA, passkeys and Face
 * ID will not work at all — browsers only offer them in a secure context.
 *
 * The card only appears when the certificate actually exists, which is only
 * under the LAN-HTTPS overlay. Everywhere else it would be an instruction you
 * cannot follow.
 *
 * The link deliberately points at the RAW endpoint rather than fetching and
 * re-serving it: iOS starts its install flow from a navigation, and an
 * XHR-fetched blob does not trigger it.
 */
export function TrustCertCard() {
  // A HEAD would be tidier, but the route only answers GET; this is a few
  // hundred bytes and the answer is cached for the page's life.
  const { data: available } = useQuery({
    queryKey: ['ca-certificate', 'available'],
    queryFn: async () => {
      try {
        await apiFetch<unknown>('/api/public/ca-certificate');
        return true;
      } catch {
        return false;
      }
    },
    retry: false,
  });

  if (!available) return null;

  return (
    <div className="card mb-3">
      <div className="card-body">
        <h5 className="card-title">Trust this device</h5>
        <p className="text-secondary small">
          <code>headroom.local</code> uses a certificate this server issued
          itself, so each device has to trust it once. Until then Face ID and
          passkeys won&rsquo;t be offered at all — browsers only allow them on a
          trusted connection.
        </p>

        <a
          href="/api/public/ca-certificate"
          className="btn btn-primary btn-sm"
          download="headroom-ca.crt"
        >Install the certificate</a>

        <p className="text-secondary small mt-3 mb-1">
          <strong>iPhone / iPad:</strong> tap the button, then{' '}
          <em>Settings → Profile Downloaded → Install</em>. Then — the step
          everyone misses — turn it on under{' '}
          <em>Settings → General → About → Certificate Trust Settings</em>.
        </p>
        <p className="text-secondary small mb-0">
          This is the <strong>root</strong> certificate. If you previously
          tried to install an <em>intermediate</em> one and it appeared to do
          nothing, that is why: an intermediate isn&rsquo;t a trust anchor, so
          installing it changes nothing.
        </p>
      </div>
    </div>
  );
}
