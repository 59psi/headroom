import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { MdnsCard } from './MdnsCard';
import * as api from '../../api/settings';
import type { MdnsStatus } from '../../types';

vi.mock('../../api/settings', () => ({
  getMdnsStatus: vi.fn(),
}));

const mocked = vi.mocked(api);

function status(over: Partial<MdnsStatus> = {}): MdnsStatus {
  return {
    enabled: true,
    advertising: true,
    hostname: 'headroom.local',
    port: 443,
    ip: '10.0.111.4',
    ipv6: '2600:6c52:7500:a7b:7e16:6b7c:551a:2d40',
    url: 'https://headroom.local',
    error: null,
    ...over,
  };
}

beforeEach(() => { vi.clearAllMocks(); });

describe('MdnsCard', () => {
  it('presents the two addresses as a matched pair, not one buried in a label', async () => {
    // The card reads as THREE facts — a state, the name devices resolve, and
    // the addresses behind it — and used to be forced through `hr-metric`'s
    // two slots. That fused the state and the IPv4 into one label
    // ("Advertising → 10.0.111.4") and left the IPv6 bolted underneath, so two
    // addresses of the same kind read as two unrelated things.
    mocked.getMdnsStatus.mockResolvedValue(status());
    renderWithProviders(<MdnsCard />);

    expect(await screen.findByText('IPv4')).toBeInTheDocument();
    expect(screen.getByText('IPv6')).toBeInTheDocument();
    expect(screen.getByText('10.0.111.4')).toBeInTheDocument();
    expect(screen.getByText('2600:6c52:7500:a7b:7e16:6b7c:551a:2d40')).toBeInTheDocument();

    // The address is its own value, no longer smuggled into the status line.
    expect(screen.queryByText(/Advertising → 10\.0\.111\.4/)).not.toBeInTheDocument();
  });

  it('keeps the resolvable name as the thing you actually click', async () => {
    mocked.getMdnsStatus.mockResolvedValue(status());
    renderWithProviders(<MdnsCard />);

    expect(await screen.findByRole('link', { name: 'https://headroom.local' }))
      .toHaveAttribute('href', 'https://headroom.local');
  });

  it('states a missing IPv6 rather than omitting the row', async () => {
    // The absence IS the diagnosis: with no IPv6 record every lookup of the
    // name stalls for the client's full resolver timeout, which reads as a slow
    // or dead site rather than a missing record. An omitted row would hide it.
    mocked.getMdnsStatus.mockResolvedValue(status({ ipv6: null }));
    renderWithProviders(<MdnsCard />);

    expect(await screen.findByText('IPv6')).toBeInTheDocument();
    expect(screen.getByText(/none on this host/)).toBeInTheDocument();
  });

  it('does not claim to be advertising when it is only enabled', async () => {
    mocked.getMdnsStatus.mockResolvedValue(status({ advertising: false }));
    renderWithProviders(<MdnsCard />);

    expect(await screen.findByText(/Enabled — not advertising/)).toBeInTheDocument();
    // No addresses to show when nothing is being advertised.
    expect(screen.queryByText('IPv4')).not.toBeInTheDocument();
  });
});
