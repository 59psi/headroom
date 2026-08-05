import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { SettingsPage } from './SettingsPage';
import { AnthropicKeyCard } from '../components/settings/AnthropicKeyCard';
import * as settingsApi from '../api/settings';
import type { ApiKeyStatus } from '../types';

vi.mock('../api/settings', () => ({
  getLogo: vi.fn(async () => ({ logo_path: null })),
  uploadLogo: vi.fn(), deleteLogo: vi.fn(),
  getApiKeyStatus: vi.fn(async () => ({ configured: true, source: 'database', masked: 'sk-an…wxyz' })),
  setApiKey: vi.fn(), deleteApiKey: vi.fn(),
  testApiKey: vi.fn(async () => ({ ok: true, detail: 'Reachable.' })),
  getGoogleVisionKeyStatus: vi.fn(async () => ({ configured: false, source: null, masked: null })),
  setGoogleVisionKey: vi.fn(), deleteGoogleVisionKey: vi.fn(),
  getModel: vi.fn(async () => ({ model_id: 'claude-sonnet-4-6', source: 'default' })),
  setModel: vi.fn(), clearModel: vi.fn(),
  getMdnsStatus: vi.fn(async () => ({
    enabled: true, advertising: true, hostname: 'headroom.local', port: 8000,
    ip: '192.168.1.20', url: 'http://headroom.local:8000',
  })),
  getRecentErrors: vi.fn(async () => []),
  listBackups: vi.fn(async () => []),
  backupDownloadUrl: vi.fn(() => '/api/admin/backup'),
  getActivityLog: vi.fn(async () => []),
  getEbayCreds: vi.fn(async () => ({ configured: false, marketplace: 'EBAY_US' })),
  setEbayCreds: vi.fn(), deleteEbayCreds: vi.fn(), testEbayCreds: vi.fn(),
  inventoryReportUrl: vi.fn(() => '/api/admin/inventory-report'),
}));

vi.mock('../api/auth', () => ({
  getMe: vi.fn(async () => ({ username: 'owner', api_token: 'hr_secret' })),
  listPasskeys: vi.fn(async () => []),
  listShareLinks: vi.fn(async () => []),
  changePassword: vi.fn(), rotateApiToken: vi.fn(), deletePasskey: vi.fn(),
  passkeyRegisterOptions: vi.fn(), passkeyRegisterVerify: vi.fn(), logout: vi.fn(),
  createShareLink: vi.fn(), revokeShareLink: vi.fn(),
}));

vi.mock('../api/client', () => ({ apiFetch: vi.fn(async () => []) }));
vi.mock('../lib/webauthn', () => ({
  createPasskey: vi.fn(), passkeysSupported: vi.fn(() => false),
}));

/** Every card the page is expected to compose, in on-screen order. */
const CARD_TITLES = [
  'Claude API Key',
  'Claude Model',
  'Google Vision Key (fallback)',
  'Recent Analysis Errors',
  'eBay Comparable Listings (optional)',
  'LAN Discovery (mDNS)',
  'Recent Activity',
  'Share Photos to Headroom',
  'Inventory Report',
  'Backups',
  'Site Logo',
  'Colorway Catalog',
  'Purchase History',
  'Account',
  'Share Links',
];

beforeEach(() => { vi.clearAllMocks(); });

describe('SettingsPage', () => {
  it('renders every card, in the documented order', async () => {
    // The page is a composition root over 15 modules; dropping one is a silent
    // failure nothing else in the toolchain catches. Scoped to `.card-title`
    // because card *bodies* mention other cards by name (ShareTargetCard points
    // at "Account"), so a bare text query is ambiguous.
    const { container } = renderWithProviders(<SettingsPage />);
    await screen.findByText('Share Links');

    const rendered = [...container.querySelectorAll('.card-title')]
      .map(el => el.textContent?.trim() ?? '');
    expect(rendered).toEqual(CARD_TITLES);
  });

  it("surfaces data from each card's own query rather than a page-level fetch", async () => {
    renderWithProviders(<SettingsPage />);
    expect(await screen.findByText('sk-an…wxyz')).toBeInTheDocument();       // key card
    expect(await screen.findByText('claude-sonnet-4-6')).toBeInTheDocument(); // model card
    expect(await screen.findByText('http://headroom.local:8000')).toBeInTheDocument(); // mDNS card
    expect(await screen.findByText(/Signed in as/)).toBeInTheDocument();      // account card
  });
});

describe('AnthropicKeyCard loading guard', () => {
  it('never claims "No key configured" while the status is still loading', async () => {
    // Regression guard for the SettingsPage split: the page used to hold one
    // spinner over every card. Per-card state without this would flash the
    // wrong answer at someone who does have a key configured.
    let release!: (v: ApiKeyStatus) => void;
    vi.mocked(settingsApi.getApiKeyStatus).mockReturnValueOnce(
      new Promise(resolve => { release = resolve; }) as ReturnType<typeof settingsApi.getApiKeyStatus>,
    );

    renderWithProviders(<AnthropicKeyCard />);

    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText('No key configured.')).not.toBeInTheDocument();

    release({ configured: true, source: 'database', masked: 'sk-an…wxyz' });
    expect(await screen.findByText('sk-an…wxyz')).toBeInTheDocument();
    expect(screen.queryByText('No key configured.')).not.toBeInTheDocument();
  });

  it('does say so once loading finishes with no key', async () => {
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValueOnce({ configured: false, source: null, masked: null });
    renderWithProviders(<AnthropicKeyCard />);
    expect(await screen.findByText('No key configured.')).toBeInTheDocument();
  });

  it('drops a stale test result when the active model changes', async () => {
    // The result is only meaningful for the model it ran against. Before the
    // split this was cleared by the Model card reaching into shared state.
    const user = userEvent.setup();
    const { client } = renderWithProviders(<AnthropicKeyCard />);
    await screen.findByText('sk-an…wxyz');

    await user.click(screen.getByRole('button', { name: /test connection/i }));
    expect(await screen.findByText(/Reachable\./)).toBeInTheDocument();

    // Simulate the Model card saving a different model.
    vi.mocked(settingsApi.getModel).mockResolvedValue({ model_id: 'claude-opus-4-7', source: 'database' });
    await client.invalidateQueries({ queryKey: ['settings', 'model'] });

    await waitFor(() => {
      expect(screen.queryByText(/Reachable\./)).not.toBeInTheDocument();
    });
  });
});
