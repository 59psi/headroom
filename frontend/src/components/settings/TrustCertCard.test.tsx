/**
 * The card that hands you Caddy's root certificate.
 *
 * It must not appear on installs that have no local CA — that is every
 * deployment except the LAN-HTTPS overlay, and an instruction you cannot
 * follow is worse than no instruction.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { TrustCertCard } from './TrustCertCard';
import * as client from '../../api/client';
import * as settingsApi from '../../api/settings';
import type { TlsStatus } from '../../types';

vi.mock('../../api/client', () => ({ apiFetch: vi.fn() }));
vi.mock('../../api/settings', () => ({ getTlsStatus: vi.fn() }));

const mocked = vi.mocked(client);
const tlsApi = vi.mocked(settingsApi);

function tls(over: Partial<TlsStatus> = {}): TlsStatus {
  return {
    applicable: true, host: 'headroom.local', port: 443,
    not_before: '2026-08-23T22:44:33Z', not_after: '2026-08-24T10:44:33Z',
    days_remaining: 0.5, expired: false, needs_attention: false,
    hostname_ok: true, ca_sha256: 'CB:08:88:5B:FD:B7:F7:DD', error: null, ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  tlsApi.getTlsStatus.mockResolvedValue(tls());
});

describe('TrustCertCard', () => {
  it('appears when the server has a local CA', async () => {
    mocked.apiFetch.mockResolvedValue('cert');

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText('Trust this device')).toBeInTheDocument();
  });

  it('stays hidden when there is no local CA', async () => {
    // Every deployment except the LAN-HTTPS overlay.
    mocked.apiFetch.mockRejectedValue(new Error('404'));

    const { container } = renderWithProviders(<TrustCertCard />);

    await vi.waitFor(() => expect(mocked.apiFetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('links straight at the endpoint rather than fetching a blob', async () => {
    // iOS starts its install flow from a navigation; an XHR-fetched blob
    // never triggers it.
    mocked.apiFetch.mockResolvedValue('cert');

    renderWithProviders(<TrustCertCard />);

    const link = await screen.findByRole('link', { name: /install the certificate/i });
    expect(link).toHaveAttribute('href', '/api/public/ca-certificate');
  });

  it('says outright when the SERVED certificate has expired', async () => {
    // The 37-day silence this was written for. Trusting the issuer does
    // nothing for an expired leaf, so the card has to say so before it tells
    // you to install anything — otherwise the instructions look broken and
    // the certificate looks fine, which is exactly backwards.
    mocked.apiFetch.mockResolvedValue('cert');
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
    mocked.apiFetch.mockResolvedValue('cert');
    tlsApi.getTlsStatus.mockResolvedValue(
      tls({ expired: false, needs_attention: true, days_remaining: 11.4 }),
    );

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText(/expires in 11 days/i)).toBeInTheDocument();
  });

  it('flags a certificate that does not cover the name it is served under', async () => {
    mocked.apiFetch.mockResolvedValue('cert');
    tlsApi.getTlsStatus.mockResolvedValue(tls({ hostname_ok: false }));

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText(/doesn[’']t cover/i)).toBeInTheDocument();
  });

  it('says nothing alarming when the certificate is healthy', async () => {
    mocked.apiFetch.mockResolvedValue('cert');

    renderWithProviders(<TrustCertCard />);
    await screen.findByText('Trust this device');

    expect(screen.queryByText(/EXPIRED/)).not.toBeInTheDocument();
    expect(screen.getByText(/good until/i)).toBeInTheDocument();
  });

  it('gives the Mac command that avoids the iCloud-keychain trap', async () => {
    // -26276 reads like a bad file rather than a wrong destination, and the
    // command never has to guess which keychain you meant.
    mocked.apiFetch.mockResolvedValue('cert');

    renderWithProviders(<TrustCertCard />);

    expect(await screen.findByText(/add-trusted-cert/)).toBeInTheDocument();
    expect(screen.getByText(/-26276/)).toBeInTheDocument();
  });

  it('says why an intermediate did nothing', async () => {
    // The reported symptom: installing the neighbouring intermediate.crt
    // appears to succeed and changes nothing.
    mocked.apiFetch.mockResolvedValue('cert');

    renderWithProviders(<TrustCertCard />);

    // `&rsquo;` renders as a curly apostrophe, so match either form rather
    // than pinning the entity's output.
    expect(
      await screen.findByText(/isn[’']t a trust anchor/i),
    ).toBeInTheDocument();
  });
});
