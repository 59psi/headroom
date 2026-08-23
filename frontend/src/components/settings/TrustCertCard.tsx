import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../../api/client';
import { getTlsStatus } from '../../api/settings';

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

  // What the front door is actually SERVING, which is a different question
  // from whether this device trusts the issuer — and the one that went
  // unanswered while an expired certificate was served for 37 days.
  const { data: tls } = useQuery({
    queryKey: ['settings', 'tls'],
    queryFn: getTlsStatus,
    retry: false,
    // Short-lived certificates renew continuously, so a cached answer here
    // ages badly; this is cheap and only runs while Settings is open.
    staleTime: 60_000,
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

        {/* Trusting the issuer does nothing for an EXPIRED leaf, so this has
            to be said before the install button rather than after it —
            otherwise the instructions look broken and the certificate looks
            fine, which is exactly backwards. */}
        {tls?.applicable && tls.needs_attention && (
          <p className="small mb-3" style={{ color: 'var(--neon-pink, #ff4fa3)' }}>
            <strong>
              {tls.expired
                ? 'The certificate being served has EXPIRED.'
                : 'The certificate being served expires within hours.'}
            </strong>{' '}
            {tls.not_after && <>It ran out {new Date(tls.not_after).toLocaleString()}. </>}
            Installing this CA will not help until it is reissued — these are
            short-lived certificates that renew themselves, so one this old
            means renewal has stopped. Restart the Caddy container
            (<code>docker restart headroom-caddy</code>) and reload.
          </p>
        )}
        {tls?.applicable && tls.hostname_ok === false && (
          <p className="small mb-3" style={{ color: 'var(--neon-pink, #ff4fa3)' }}>
            The certificate being served doesn&rsquo;t cover{' '}
            <code>{tls.host}</code>, so browsers will refuse it however it is
            trusted.
          </p>
        )}

        <a
          href="/api/public/ca-certificate"
          className="btn btn-primary btn-sm"
          download="headroom-ca.crt"
        >Install the certificate</a>

        {tls?.applicable && !tls.needs_attention && tls.not_after && (
          <p className="text-secondary small mt-2 mb-0" style={{ fontSize: '0.72rem' }}>
            Currently serving a valid certificate for <code>{tls.host}</code>,
            good until {new Date(tls.not_after).toLocaleString()}.
          </p>
        )}

        <p className="text-secondary small mt-3 mb-1">
          <strong>iPhone / iPad:</strong> tap the button, then{' '}
          <em>Settings → Profile Downloaded → Install</em>. Then — the step
          everyone misses — turn it on under{' '}
          <em>Settings → General → About → Certificate Trust Settings</em>.
        </p>
        {/* Caddy names every root `Caddy Local Authority - <year> ECC Root`,
            so a second install produces a DIFFERENT root with the SAME name.
            A browser matching by name picks whichever it has and reports
            "invalid signature" on a chain that verifies fine at the server —
            and nothing separates the two by eye. This does. */}
        {tls?.ca_sha256 && (
          <p className="text-secondary small mt-3 mb-1">
            <strong>This CA&rsquo;s fingerprint (SHA-256):</strong>{' '}
            <code style={{ fontSize: '0.68rem', wordBreak: 'break-all' }}>
              {tls.ca_sha256}
            </code>
            <br />
            Still refused after installing? You may be trusting an{' '}
            <em>older</em> Caddy root &mdash; they all carry the same name, so
            only this fingerprint tells them apart. List what your Mac has with{' '}
            <code style={{ fontSize: '0.68rem' }}>
              security find-certificate -a -c Caddy -Z
              /Library/Keychains/System.keychain | grep SHA-256
            </code>{' '}
            and delete any that don&rsquo;t match, plus any{' '}
            <em>Intermediate</em>, with{' '}
            <code style={{ fontSize: '0.68rem' }}>
              sudo security delete-certificate -Z &lt;sha1&gt;
              /Library/Keychains/System.keychain
            </code>.
          </p>
        )}

        <p className="text-secondary small mb-1">
          <strong>Mac:</strong> one command imports and trusts it without you
          having to pick a keychain —{' '}
          <code style={{ fontSize: '0.72rem' }}>
            sudo security add-trusted-cert -d -r trustRoot -k
            /Library/Keychains/System.keychain headroom-ca.crt
          </code>. Double-clicking works too, but only into{' '}
          <em>login</em> or <em>System</em>: the <em>iCloud</em> keychain
          can&rsquo;t hold certificates and rejects it with{' '}
          <code>Error: -26276</code>, which reads like a bad file rather than
          the wrong destination.
        </p>
        <p className="text-secondary small mb-0">
          This is the <strong>root</strong> certificate. If you previously
          tried to install an <em>intermediate</em> one and it appeared to do
          nothing, that is why: an intermediate isn&rsquo;t a trust anchor, so
          installing it changes nothing. A browser&rsquo;s own
          &ldquo;export&rdquo; button always hands you the leaf or the
          intermediate, never the root &mdash; a root is self-signed and never
          sent during a handshake, so it can only come from here.
        </p>
      </div>
    </div>
  );
}
