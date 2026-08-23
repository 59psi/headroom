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

vi.mock('../../api/client', () => ({ apiFetch: vi.fn() }));

const mocked = vi.mocked(client);

beforeEach(() => vi.clearAllMocks());

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
