/**
 * The card that hands you Caddy's root certificate.
 *
 * It must not appear on installs that have no local CA — that is every
 * deployment except the LAN-HTTPS overlay, and an instruction you cannot
 * follow is worse than no instruction.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { TrustCertCard } from './TrustCertCard';
import * as settingsApi from '../../api/settings';
import * as clipboard from '../../lib/clipboard';
import type { TlsStatusRead } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getTlsStatus: vi.fn(), caCertificateAvailable: vi.fn()
  };
});
vi.mock('../../lib/clipboard', () => ({ copyText: vi.fn() }));

const tlsApi = vi.mocked(settingsApi);
const copyText = vi.mocked(clipboard.copyText);

function tls(over: Partial<TlsStatusRead> = {}): TlsStatusRead {
  return {
    applicable: true, host: 'headroom.local', port: 443,
    not_before: '2026-08-23T22:44:33Z', not_after: '2026-08-24T10:44:33Z',
    days_remaining: 0.5, expired: false, needs_attention: false,
    hostname_ok: true, ca_sha256: 'CB:08:88:5B:FD:B7:F7:DD', chain_matches_ca: true,
    error: null, ca_changed: false, ca_expected_sha256: 'CB:08:88:5B:FD:B7:F7:DD',
    issuer_not_after: '2034-11-12T00:00:00Z', clamped_by_issuer: false, ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  tlsApi.getTlsStatus.mockResolvedValue(tls());
});

describe('TrustCertCard', () => {
  it('appears when the server has a local CA', async () => {
    tlsApi.caCertificateAvailable.mockResolvedValue(true);

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText('Trust this device')).toBeInTheDocument();
  });

  it('stays hidden when there is no local CA', async () => {
    // Every deployment except the LAN-HTTPS overlay.
    tlsApi.caCertificateAvailable.mockResolvedValue(false);

    const { container } = renderWithProviders(<TrustCertCard />);

    await vi.waitFor(() => expect(tlsApi.caCertificateAvailable).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('links straight at the endpoint rather than fetching a blob', async () => {
    // iOS starts its install flow from a navigation; an XHR-fetched blob
    // never triggers it.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);

    renderWithProviders(<TrustCertCard />);

    const link = await screen.findByRole('link', { name: /install the certificate/i });
    expect(link).toHaveAttribute('href', '/api/public/ca-certificate');
  });

  it('says outright when the SERVED certificate has expired', async () => {
    // The 37-day silence this was written for. Trusting the issuer does
    // nothing for an expired leaf, so the card has to say so before it tells
    // you to install anything — otherwise the instructions look broken and
    // the certificate looks fine, which is exactly backwards.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(
      tls({ expired: true, needs_attention: true, days_remaining: -37.6 }),
    );

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText(/certificate being served has EXPIRED/i)).toBeInTheDocument();
    expect(screen.getByText(/docker restart headroom-caddy/)).toBeInTheDocument();
  });

  it('warns before expiry too, because renewal stopping is the real signal', async () => {
    // Certificates here are issued for 820 days (see ./Caddyfile) and Caddy
    // renews at a third of that remaining, so being inside the grace window
    // means renewal has stopped — not that expiry is merely approaching. The
    // warning has to name the real number of days: "expires within hours" was
    // true of the old twelve-hour certificates and is now off by a month.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(
      tls({ expired: false, needs_attention: true, days_remaining: 11.4 }),
    );

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText(/expires in 11 days/i)).toBeInTheDocument();
  });

  it('flags a certificate that does not cover the name it is served under', async () => {
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(tls({ hostname_ok: false }));

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText(/doesn[’']t cover/i)).toBeInTheDocument();
  });

  it('says nothing alarming when the certificate is healthy', async () => {
    tlsApi.caCertificateAvailable.mockResolvedValue(true);

    renderWithProviders(<TrustCertCard />);
    await screen.findByText('Trust this device');

    // Case-insensitive now that the alarm is sentence case ("has expired"):
    // the pill and the alert box carry the emphasis the capitals used to.
    expect(await screen.findByText(/good until/i)).toBeInTheDocument();
    expect(screen.queryByText(/has expired/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/expires in/i)).not.toBeInTheDocument();
    expect(screen.getByText('Valid')).toBeInTheDocument();
  });

  it('gives the Mac command that avoids the iCloud-keychain trap', async () => {
    // -26276 reads like a bad file rather than a wrong destination, and the
    // command never has to guess which keychain you meant.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText(/add-trusted-cert/)).toBeInTheDocument();
    expect(screen.getByText(/-26276/)).toBeInTheDocument();
  });

  it('says why an intermediate did nothing', async () => {
    // The reported symptom: installing the neighboring intermediate.crt
    // appears to succeed and changes nothing.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);

    renderWithProviders(<TrustCertCard />);

    // `&rsquo;` renders as a curly apostrophe, so match either form rather
    // than pinning the entity's output.
    expect(
      await screen.findByText(/isn[’']t a trust anchor/i),
    ).toBeInTheDocument();
  });

  it('raises the alarm when the authority itself was replaced', async () => {
    // Categorically worse than expiry and fixed differently: a leaf reissues
    // itself, a hand-installed root has to be reinstalled on every device.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(tls({
      ca_changed: true,
      ca_sha256: 'NEW:FF:EE',
      ca_expected_sha256: 'OLD:AA:BB',
    }));

    renderWithProviders(<TrustCertCard />);

    expect(
      await screen.findByText(/certificate authority has changed/i),
    ).toBeInTheDocument();
    // Both fingerprints, because Caddy gives every root the same NAME — these
    // are the only thing that tells the two apart. `getAllBy` for the served
    // one: the card also prints it in its own fingerprint row further down,
    // which is correct and not what this test is about.
    expect(screen.getByText(/OLD:AA:BB/)).toBeInTheDocument();
    expect(screen.getAllByText(/NEW:FF:EE/).length).toBeGreaterThan(0);
    // The cheap way out, if a backup predates the change.
    expect(screen.getByText(/caddy-pki/)).toBeInTheDocument();
  });

  it('names the intermediate when the leaf was clamped, not merely expiring', async () => {
    // The real incident: Caddy issued SIX-day certs against a configured 820
    // because the intermediate had seven days left. The card correctly warned
    // about a short certificate and then advised restarting Caddy -- which
    // reissues another six-day cert. Same symptom, opposite fix.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(tls({
      needs_attention: true, days_remaining: 4.2,
      clamped_by_issuer: true, issuer_not_after: '2026-08-30T05:31:42Z',
    }));

    renderWithProviders(<TrustCertCard />);

    expect(
      await screen.findByText(/cut short to match the intermediate/i),
    ).toBeInTheDocument();
    // The advice that would have looped must NOT be the headline here.
    expect(screen.getByText(/restarting Caddy alone does not fix this/i)).toBeInTheDocument();
    // And the reassurance that makes the fix safe to run.
    expect(screen.getByText(/root is untouched/i)).toBeInTheDocument();
  });

  it('catches a served chain from another authority behind a perfect root file', async () => {
    // The CA-restore state: root.crt is the original authority (so no
    // "changed"), the leaf is valid and covers the name — and it was signed
    // by the authority Caddy minted in between, so every device refuses it.
    // This card used to show "Currently serving a valid certificate" here.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(tls({ chain_matches_ca: false, days_remaining: 700 }));

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText(/served is from a different authority/i)).toBeInTheDocument();
    expect(screen.getByText('Wrong authority')).toBeInTheDocument();
    expect(screen.queryByText('Valid')).not.toBeInTheDocument();
    expect(screen.queryByText(/good until/i)).not.toBeInTheDocument();
    expect(screen.getByText(/rm -rf \/data\/caddy\/certificates\/local/)).toBeInTheDocument();
  });

  it('labels the fingerprint as served only once the chain has been checked', async () => {
    // `ca_sha256` is the exported root file. When the served chain was not
    // (or could not be) checked against it, "now serving" is a claim nobody
    // verified.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(tls({
      ca_changed: true, ca_sha256: 'NEW:FF:EE', ca_expected_sha256: 'OLD:AA:BB',
      chain_matches_ca: null,
    }));

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText('Now handing out')).toBeInTheDocument();
    expect(screen.queryByText('Now serving')).not.toBeInTheDocument();
  });

  it('stays quiet when the authority is the one the devices trust', async () => {
    tlsApi.caCertificateAvailable.mockResolvedValue(true);

    renderWithProviders(<TrustCertCard />);

    await screen.findByText(/Install the certificate/i);
    expect(screen.queryByText(/certificate authority has changed/i)).toBeNull();
    expect(screen.queryByText(/from a different authority/i)).toBeNull();
  });
});

describe('TrustCertCard — the header verdict', () => {
  it('ranks a replaced authority above an expiry, as the alerts do', async () => {
    // Both are true here; the pill names the one with the bigger blast
    // radius (every device locked out) rather than the one listed first.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(tls({
      ca_changed: true, ca_sha256: 'NEW:FF:EE', ca_expected_sha256: 'OLD:AA:BB',
      expired: true, needs_attention: true, days_remaining: -3,
    }));

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText('CA changed')).toBeInTheDocument();
    expect(screen.queryByText('Expired')).not.toBeInTheDocument();
  });

  it('says Expired for an expired leaf', async () => {
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(
      tls({ expired: true, needs_attention: true, days_remaining: -37.6 }),
    );

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText('Expired')).toBeInTheDocument();
  });

  it('counts the days left once renewal has stopped', async () => {
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(
      tls({ needs_attention: true, days_remaining: 11.4 }),
    );

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText('11 days left')).toBeInTheDocument();
  });

  it('claims nothing while the served certificate is still being read', async () => {
    // A "Valid" pill before the answer arrives would be the exact reassurance
    // the 37-day incident was made of.
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockReturnValue(new Promise(() => {}));

    renderWithProviders(<TrustCertCard />);

    await screen.findByText('Trust this device');
    expect(screen.getByRole('status')).toHaveTextContent('Loading…');
    expect(screen.queryByText('Valid')).not.toBeInTheDocument();
  });

  it('does not stay silent when the server could not read its own certificate', async () => {
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(tls({
      not_after: null, days_remaining: null, hostname_ok: null,
      error: 'Connection refused',
    }));

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText('Can’t check')).toBeInTheDocument();
    expect(screen.getByText(/Connection refused/)).toBeInTheDocument();
    expect(screen.queryByText('Valid')).not.toBeInTheDocument();
  });
});

describe('TrustCertCard — copying', () => {
  it('copies the fingerprint exactly, and says so in place', async () => {
    const user = userEvent.setup();
    copyText.mockResolvedValue(true);
    tlsApi.caCertificateAvailable.mockResolvedValue(true);

    renderWithProviders(<TrustCertCard />);
    await user.click(await screen.findByRole('button', { name: 'Copy the fingerprint' }));

    expect(copyText).toHaveBeenCalledWith('CB:08:88:5B:FD:B7:F7:DD');
    expect(screen.getByRole('button', { name: 'Copied the fingerprint' })).toHaveTextContent('Copied');
  });

  it('copies the whole Mac command, not the sentence around it', async () => {
    const user = userEvent.setup();
    copyText.mockResolvedValue(true);
    tlsApi.caCertificateAvailable.mockResolvedValue(true);

    renderWithProviders(<TrustCertCard />);
    await user.click(await screen.findByRole('button', { name: 'Copy the Mac trust command' }));

    expect(copyText).toHaveBeenCalledWith(
      'sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain headroom-ca.crt',
    );
  });

  it('copies an intermediate fix that names the files, with no glob to fail', async () => {
    // `docker exec` runs `rm` with no shell, so `intermediate.*` is only ever
    // expanded on the HOST, where it matches nothing: zsh aborted the chain,
    // bash passed `rm -f` a literal and restarted Caddy onto the same short
    // intermediate. The copied text is the fix, so it has to work verbatim.
    const user = userEvent.setup();
    copyText.mockResolvedValue(true);
    tlsApi.caCertificateAvailable.mockResolvedValue(true);
    tlsApi.getTlsStatus.mockResolvedValue(tls({
      needs_attention: true, days_remaining: 4.2,
      clamped_by_issuer: true, issuer_not_after: '2026-08-30T05:31:42Z',
    }));

    renderWithProviders(<TrustCertCard />);
    await user.click(await screen.findByRole('button', { name: 'Copy the intermediate-replacement command' }));

    const copied = copyText.mock.calls[0][0];
    expect(copied).not.toContain('*');
    expect(copied).toContain('/data/caddy/pki/authorities/local/intermediate.crt');
    expect(copied).toContain('/data/caddy/pki/authorities/local/intermediate.key');
    expect(copied).toContain('rm -rf /data/caddy/certificates/local');
    expect(copied).toMatch(/&& docker restart headroom-caddy$/);
    // The root is what every device trusts; the fix must never touch it.
    expect(copied).not.toMatch(/root\./);
  });

  it('tells you when the browser refused to copy', async () => {
    const user = userEvent.setup();
    copyText.mockResolvedValue(false);
    tlsApi.caCertificateAvailable.mockResolvedValue(true);

    renderWithProviders(<TrustCertCard />);
    await user.click(await screen.findByRole('button', { name: 'Copy the fingerprint' }));

    expect(await screen.findByText(/Couldn’t copy the fingerprint/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Copied the fingerprint' })).not.toBeInTheDocument();
  });
});
