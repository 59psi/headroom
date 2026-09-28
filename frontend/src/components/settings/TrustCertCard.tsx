import { useQuery } from '@tanstack/react-query';
import { CA_CERTIFICATE_URL, caCertificateAvailable, getTlsStatus } from '../../api/settings';
import type { TlsStatusRead } from '../../types';
import { plural } from '../../lib/format';
import { qk } from '../../lib/queryKeys';
import { ErrorNote } from '../common/ErrorNote';
import { Panel } from '../ui/Panel';
import { CopyButton } from '../ui/CopyButton';
import { Skeleton } from '../ui/Skeleton';
import { StatusPill } from '../ui/StatusPill';

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
 *
 * Layout: what is wrong (if anything) → the one button → the per-device steps
 * that follow it → the fingerprint. Everything that is only needed when the
 * steps did not work — keychain traps, stale roots, intermediates — is folded
 * behind "Troubleshooting", because on a healthy install it was two thirds of
 * the card and none of it applied.
 */
export function TrustCertCard() {
  // A HEAD would be tidier, but the route only answers GET (FastAPI does not
  // add HEAD for free); this is a kilobyte and the answer is cached for the
  // page's life. See `caCertificateAvailable` for why it is not `apiFetch`.
  const { data: available } = useQuery({
    queryKey: qk.caCertificateAvailable(),
    queryFn: caCertificateAvailable,
    retry: false,
  });

  // What the front door is actually SERVING, which is a different question
  // from whether this device trusts the issuer — and the one that went
  // unanswered while an expired certificate was served for 37 days.
  const tlsQuery = useQuery({
    queryKey: qk.settings.tls(),
    queryFn: getTlsStatus,
    retry: false,
    // Short enough that restarting Caddy and reloading shows the new
    // certificate rather than the cached verdict on the old one — which is
    // the one thing this card ever asks anybody to do.
    staleTime: 60_000,
  });
  const tls = tlsQuery.data;

  // No skeleton while the probe is in flight, unlike every other card: on
  // every deployment but one the answer is "no CA here", so a placeholder
  // would flash a card that then vanishes. Absent until proven present.
  if (!available) return null;

  const days = Math.max(0, Math.floor(tls?.days_remaining ?? 0));

  return (
    <Panel
      title="Trust this device"
      status={certPill(tls)}
      description="Each device has to trust this server’s own certificate once — until then, no Face ID or passkeys."
      helpLabel="Troubleshooting"
      help={<TrustHelp />}
    >
      <ErrorNote of={tlsQuery} what="Could not read the served certificate" className="mb-3" />

      {/* Louder than expiry, and above it, because it is a bigger problem
          with a different fix. An expired leaf is reissued by restarting
          Caddy; a replaced ROOT means the authority every device trusts no
          longer exists, and no amount of restarting brings it back. (It sat
          BELOW the expiry note while this comment said above; the order now
          matches the argument, and the status pill ranks them the same way.) */}
      {tls?.ca_changed && (
        <div className="alert alert-danger hr-cert-alert">
          <strong className="hr-cert-alert-head">The certificate authority has changed.</strong>
          This install is now serving a different root than the one recorded
          when it was first set up, which means Caddy generated a fresh
          authority — so every device that trusted the old one will refuse to
          connect until it installs the new certificate below.
          <dl className="hr-cert-fp-pair">
            <dt>Your devices trust</dt>
            <dd><code>{tls.ca_expected_sha256}</code></dd>
            {/* The fingerprint is the EXPORTED root — what this server hands
                out. It is only what it serves once the served chain has been
                checked against it; the label used to claim "serving" either
                way, which was false in exactly the case below. */}
            <dt>{tls.chain_matches_ca === true ? 'Now serving' : 'Now handing out'}</dt>
            <dd><code>{tls.ca_sha256}</code></dd>
          </dl>
          If you have a backup from before this happened, restoring{' '}
          <code>caddy-pki/</code> from it puts the original authority back and
          saves re-trusting anything.
        </div>
      )}

      {/* The served chain leads to a DIFFERENT authority than the one this
          server hands out — the state a CA restore leaves behind while Caddy
          still holds a leaf from the authority it minted in between. The
          root file and the fingerprint below look perfect; the certificate
          is valid and covers the name; and every device refuses it. Said as
          loudly as a replaced root, because the effect is the same, but with
          its own fix: the authority is already right, only the leaf is not. */}
      {tls?.applicable && tls.chain_matches_ca === false && (
        <div className="alert alert-danger hr-cert-alert">
          <strong className="hr-cert-alert-head">
            The certificate being served is from a different authority.
          </strong>
          Caddy is serving a certificate that was not signed by the authority
          this server hands out below, so every device that installed it will
          refuse the connection. This happens after an authority is restored
          from a backup while Caddy still holds a certificate from the one it
          created in between. Clear its issued certificates so it reissues
          them from the restored authority — the root is untouched, so no
          device has to be re-trusted:
          <Command
            what="certificate-reissue command"
            text={
              'docker exec headroom-caddy rm -rf /data/caddy/certificates/local '
              + '&& docker restart headroom-caddy'
            }
          />
        </div>
      )}

      {/* Trusting the issuer does nothing for an EXPIRED leaf, so this has
          to be said before the install button rather than after it —
          otherwise the instructions look broken and the certificate looks
          fine, which is exactly backwards. */}
      {tls?.applicable && tls.needs_attention && (
        <div className={`alert ${tls.expired ? 'alert-danger' : 'alert-warning'} hr-cert-alert`}>
          <strong className="hr-cert-alert-head">
            {tls.expired
              ? 'The certificate being served has expired.'
              : `The certificate being served expires in ${plural(days, 'day')}.`}
          </strong>
          {tls.not_after && (
            <>
              {tls.expired ? 'It ran out' : 'It runs out'}{' '}
              {new Date(tls.not_after).toLocaleString()}.{' '}
            </>
          )}
          Installing this CA will not help until it is reissued.{' '}
          {tls.clamped_by_issuer ? (
            <>
              <strong>
                This is not the certificate&rsquo;s own age — it was cut short to
                match the intermediate that signs it
              </strong>
              , which runs out{' '}
              {tls.issuer_not_after &&
                new Date(tls.issuer_not_after).toLocaleDateString()}
              . A certificate cannot outlive its issuer, so renewing will just
              produce another short one; restarting Caddy alone does not fix
              this. Replace the intermediate — the root is untouched, so no
              device has to be re-trusted:
              {/* The two files by name, as docs/OPERATIONS.md gives them — not
                  `intermediate.*`. `docker exec` runs `rm` without a shell, so
                  nothing inside the container expands the glob, and the one
                  on the host matches nothing there: zsh and fish abort the
                  whole chain ("no matches found"), bash hands `rm -f` a
                  literal that does not exist and carries on — restarting
                  Caddy onto the SAME short intermediate. A Copy button makes
                  the exact text the fix, so the exact text has to work. */}
              <Command
                what="intermediate-replacement command"
                text={
                  'docker exec headroom-caddy rm -f '
                  + '/data/caddy/pki/authorities/local/intermediate.crt '
                  + '/data/caddy/pki/authorities/local/intermediate.key '
                  + '&& docker exec headroom-caddy rm -rf /data/caddy/certificates/local '
                  + '&& docker restart headroom-caddy'
                }
              />
            </>
          ) : (
            <>
              Caddy renews these long before this point, so a certificate this
              close to expiry means renewal has stopped rather than that expiry
              is merely approaching. Restart the Caddy container and reload:
              <Command what="restart command" text="docker restart headroom-caddy" />
            </>
          )}
        </div>
      )}

      {tls?.applicable && tls.hostname_ok === false && (
        <div className="alert alert-danger hr-cert-alert">
          The certificate being served doesn&rsquo;t cover{' '}
          <code>{tls.host}</code>, so browsers will refuse it however it is
          trusted.
        </div>
      )}

      <div className="hr-cert-install">
        <a
          href={CA_CERTIFICATE_URL}
          className="btn btn-primary"
          download="headroom-ca.crt"
        >Install the certificate</a>
        {tlsQuery.isLoading ? (
          <Skeleton lines={1} width="14rem" className="hr-cert-serving" />
        ) : tls?.applicable && !tls.needs_attention && tls.chain_matches_ca !== false && tls.not_after ? (
          <p className="hr-cert-serving">
            Currently serving a valid certificate for <code>{tls.host}</code>,
            good until {new Date(tls.not_after).toLocaleString()}.
          </p>
        ) : tls?.applicable && tls.error ? (
          // The server could not reach its own front door to look. Said here
          // rather than dropped: "no warning" must not read as "all clear".
          <p className="hr-cert-serving">
            Couldn&rsquo;t read the certificate being served: {tls.error}
          </p>
        ) : null}
      </div>

      <div className="hr-cert-steps">
        <div className="hr-cert-step">
          <span className="hr-eyebrow">iPhone / iPad</span>
          <ol className="hr-cert-step-list">
            <li>Tap the button above.</li>
            <li><em>Settings → Profile Downloaded → Install</em>.</li>
            <li>
              Then — the step everyone misses — turn it on under{' '}
              <em>Settings → General → About → Certificate Trust Settings</em>.
            </li>
          </ol>
        </div>
        <div className="hr-cert-step">
          <span className="hr-eyebrow">Mac</span>
          <p className="hr-cert-step-text">
            One command imports and trusts it without you having to pick a
            keychain:
          </p>
          <Command
            what="Mac trust command"
            text="sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain headroom-ca.crt"
          />
        </div>
      </div>

      {/* Caddy names every root `Caddy Local Authority - <year> ECC Root`,
          so a second install produces a DIFFERENT root with the SAME name.
          A browser matching by name picks whichever it has and reports
          "invalid signature" on a chain that verifies fine at the server —
          and nothing separates the two by eye. This does. */}
      {tls?.ca_sha256 && (
        <div className="hr-cert-fp">
          <span className="hr-eyebrow">This CA&rsquo;s fingerprint (SHA-256)</span>
          <div className="hr-dev-value-row">
            <code className="hr-dev-value">{tls.ca_sha256}</code>
            <CopyButton text={tls.ca_sha256} what="fingerprint" />
          </div>
        </div>
      )}
    </Panel>
  );
}

/**
 * The header pill, ranked the way the alerts are: a replaced authority first
 * (every device is locked out), then a served chain from another authority
 * (the same lockout, with the authority itself intact), then expiry, then a
 * name the certificate does not cover, then "running out". Nothing while the
 * status is unknown — a pill that said "Valid" before the answer arrived
 * would be the one lie this card exists to stop telling.
 */
function certPill(tls: TlsStatusRead | undefined) {
  if (!tls) return null;
  if (tls.ca_changed) {
    return <StatusPill tone="error" title="Devices that trusted the old root will refuse to connect">CA changed</StatusPill>;
  }
  if (!tls.applicable) return null;
  if (tls.error) {
    return <StatusPill tone="warn" title={tls.error}>Can’t check</StatusPill>;
  }
  if (tls.chain_matches_ca === false) {
    return (
      <StatusPill tone="error" title="The served certificate was not signed by the authority your devices trust">
        Wrong authority
      </StatusPill>
    );
  }
  if (tls.expired) return <StatusPill tone="error">Expired</StatusPill>;
  if (tls.hostname_ok === false) {
    return <StatusPill tone="error" title={`Doesn’t cover ${tls.host ?? 'this host'}`}>Wrong host</StatusPill>;
  }
  if (tls.needs_attention) {
    const days = Math.max(0, Math.floor(tls.days_remaining ?? 0));
    return (
      <StatusPill tone="warn" title="Renewal has evidently stopped">
        {plural(days, 'day')} left
      </StatusPill>
    );
  }
  return (
    <StatusPill
      tone="ok"
      title={tls.not_after ? `Good until ${new Date(tls.not_after).toLocaleString()}` : undefined}
    >
      Valid
    </StatusPill>
  );
}

/** Only needed when the steps above did not work. */
function TrustHelp() {
  return (
    <>
      <p>
        <code>headroom.local</code> uses a certificate this server issued
        itself. Until a device trusts it, Face ID and passkeys won&rsquo;t be
        offered at all — browsers only allow them on a trusted connection.
      </p>
      <p>
        <strong>Still refused after installing?</strong> You may be trusting an{' '}
        <em>older</em> Caddy root &mdash; they all carry the same name, so
        only this CA&rsquo;s fingerprint (at the foot of this card) tells them
        apart. List what your Mac has with
      </p>
      <Command
        what="list-certificates command"
        text="security find-certificate -a -c Caddy -Z /Library/Keychains/System.keychain | grep SHA-256"
      />
      <p>
        and delete any that don&rsquo;t match, plus any <em>Intermediate</em>, with
      </p>
      <Command
        what="delete-certificate command"
        text="sudo security delete-certificate -Z <sha1> /Library/Keychains/System.keychain"
      />
      <p>
        <strong>Double-clicking on a Mac</strong> works too, but only into{' '}
        <em>login</em> or <em>System</em>: the <em>iCloud</em> keychain
        can&rsquo;t hold certificates and rejects it with{' '}
        <code>Error: -26276</code>, which reads like a bad file rather than
        the wrong destination.
      </p>
      <p>
        This is the <strong>root</strong> certificate. If you previously
        tried to install an <em>intermediate</em> one and it appeared to do
        nothing, that is why: an intermediate isn&rsquo;t a trust anchor, so
        installing it changes nothing. A browser&rsquo;s own
        &ldquo;export&rdquo; button always hands you the leaf or the
        intermediate, never the root &mdash; a root is self-signed and never
        sent during a handshake, so it can only come from here.
      </p>
    </>
  );
}

/**
 * A shell command with a copy button. These were inline `<code>` runs broken
 * across three lines by the paragraph's wrapping — on a phone, selecting one
 * exactly (and not the sentence around it) was the hardest part of the fix.
 */
function Command({ text, what }: { text: string; what: string }) {
  return (
    <div className="hr-dev-cmd">
      <code>{text}</code>
      <CopyButton text={text} what={what} />
    </div>
  );
}

