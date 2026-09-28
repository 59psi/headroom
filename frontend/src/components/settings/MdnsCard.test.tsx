import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { MdnsCard } from './MdnsCard';
import * as api from '../../api/settings';
import * as clipboard from '../../lib/clipboard';
import type { MdnsStatus } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getMdnsStatus: vi.fn(),
  };
});
vi.mock('../../lib/clipboard', () => ({ copyText: vi.fn() }));

const mocked = vi.mocked(api);
const copyText = vi.mocked(clipboard.copyText);

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
    // The state moved from a line in the body ("Enabled — not advertising")
    // to the header pill; the guard is the same — enabled is not advertising.
    mocked.getMdnsStatus.mockResolvedValue(status({ advertising: false }));
    renderWithProviders(<MdnsCard />);

    expect(await screen.findByText('Not advertising')).toBeInTheDocument();
    expect(screen.queryByText('Advertising')).not.toBeInTheDocument();
    // No addresses to show when nothing is being advertised.
    expect(screen.queryByText('IPv4')).not.toBeInTheDocument();
  });

  it('says Advertising when it is, and Off when mDNS is disabled', async () => {
    mocked.getMdnsStatus.mockResolvedValue(status());
    const { unmount } = renderWithProviders(<MdnsCard />);
    expect(await screen.findByText('Advertising')).toBeInTheDocument();
    unmount();

    mocked.getMdnsStatus.mockResolvedValue(status({
      enabled: false, advertising: false, url: null, ip: null, ipv6: null,
    }));
    renderWithProviders(<MdnsCard />);
    expect(await screen.findByText('Off')).toBeInTheDocument();
    expect(screen.queryByText('Not advertising')).not.toBeInTheDocument();
    // The name it WOULD advertise, rather than an empty box.
    expect(screen.getByText('headroom.local')).toBeInTheDocument();
  });

  it('shows a placeholder, not an empty card or a guessed state, while loading', async () => {
    mocked.getMdnsStatus.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<MdnsCard />);

    expect(screen.getByText('LAN discovery (mDNS)')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Loading…');
    expect(screen.queryByText('Off')).not.toBeInTheDocument();
    expect(screen.queryByText('Not advertising')).not.toBeInTheDocument();
  });
});

describe('MdnsCard — copying an address', () => {
  it('copies each address on its own', async () => {
    const user = userEvent.setup();
    copyText.mockResolvedValue(true);
    mocked.getMdnsStatus.mockResolvedValue(status());
    renderWithProviders(<MdnsCard />);

    await user.click(await screen.findByRole('button', { name: 'Copy the IPv4 address' }));
    expect(copyText).toHaveBeenLastCalledWith('10.0.111.4');
    expect(screen.getByRole('button', { name: 'Copied the IPv4 address' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Copy the IPv6 address' }));
    expect(copyText).toHaveBeenLastCalledWith('2600:6c52:7500:a7b:7e16:6b7c:551a:2d40');

    await user.click(screen.getByRole('button', { name: 'Copy the address' }));
    expect(copyText).toHaveBeenLastCalledWith('https://headroom.local');
  });

  it('offers nothing to copy for a missing IPv6', async () => {
    mocked.getMdnsStatus.mockResolvedValue(status({ ipv6: null }));
    renderWithProviders(<MdnsCard />);

    await screen.findByText('IPv6');
    expect(screen.queryByRole('button', { name: /IPv6/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy the IPv4 address' })).toBeInTheDocument();
  });
});
