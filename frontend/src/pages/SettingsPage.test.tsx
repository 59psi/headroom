import type * as S from '../api/settings';
import { sweepProgressFixture } from '../test/fixtures';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { SettingsPage, SECTIONS } from './SettingsPage';
import { AnthropicKeyCard } from '../components/settings/AnthropicKeyCard';
import { ClaudeModelCard } from '../components/settings/ClaudeModelCard';
import * as settingsApi from '../api/settings';
import type { ApiKeyStatus } from '../types';

// Every export of the real module is mocked — the ones below with a payload
// of the real shape, everything else as a bare `vi.fn()`. The mock used to be
// an explicit object, so any NEW export a mounted card called failed with
// `No "<name>" export is defined on the mock` — it caught `auditSharedPrices`,
// `getUnclaimedFromPurchases` and `runRepricingAll` in three consecutive
// releases, and at 2.77.3 three more were missing (`retryFailedAnalysis`,
// `getAnalysisJob`, `refreshColorwayCatalog`), each one click away from a
// crash in a test that never clicked. Filling from the real module's keys
// makes adding a card two edits, not three.
vi.mock('../api/settings', async (importOriginal) => {
  const real = await importOriginal<typeof S>();
  const everything = Object.fromEntries(Object.keys(real).map(k => [k, vi.fn()]));
  return { ...everything, ...explicit() };
});

function explicit() {
  return {
  getLogo: vi.fn(async () => ({ logo_path: null })),
  uploadLogo: vi.fn(), deleteLogo: vi.fn(),
  getApiKeyStatus: vi.fn(async () => ({ configured: true, source: 'database', masked: 'sk-an…wxyz' })),
  setApiKey: vi.fn(), deleteApiKey: vi.fn(),
  testApiKey: vi.fn(async () => ({ ok: true, detail: 'Reachable.' })),
  getGoogleVisionKeyStatus: vi.fn(async () => ({ configured: false, source: null, masked: null })),
  setGoogleVisionKey: vi.fn(), deleteGoogleVisionKey: vi.fn(),
  getModel: vi.fn<typeof S.getModel>(async () => ({
    model_id: 'claude-sonnet-5', source: 'default', default_model_id: 'claude-sonnet-5',
  })),
  setModel: vi.fn(), clearModel: vi.fn(),
  getMdnsStatus: vi.fn(async () => ({
    enabled: true, advertising: true, hostname: 'headroom.local', port: 8000,
    ip: '192.168.1.20', ipv6: '2600:6c52:7500:a7b::99',
    url: 'http://headroom.local:8000', error: null,
  })),
  // Mock the real payload shape: pydantic serializes every field, including
  // the ones with defaults, so a partial literal here would be a fiction the
  // component is never handed in production.
  caCertificateAvailable: vi.fn(async () => false),
  getTlsStatus: vi.fn<typeof S.getTlsStatus>(async () => ({
    applicable: true, host: 'headroom.local', port: 443,
    not_before: '2026-08-23T22:44:33Z', not_after: '2026-08-24T10:44:33Z',
    days_remaining: 0.5, expired: false, needs_attention: false,
    hostname_ok: true, ca_sha256: 'CB:08:88:5B:FD:B7:F7:DD', error: null,
    ca_changed: false, ca_expected_sha256: 'CB:08:88:5B:FD:B7:F7:DD',
    issuer_not_after: '2034-11-12T00:00:00Z', clamped_by_issuer: false,
  })),
  getRecentErrors: vi.fn(async () => []),
  getAnalysisFailures: vi.fn(async () => []),
  getAnalysisQueue: vi.fn(async () => ({
    worker_alive: true, queued: 0, pending_count: 0, pending: [],
    current_job: null, recent_jobs: [],
  })),
  reanalyzeAll: vi.fn(),
  listBackups: vi.fn(async () => []),
  // The real payload shape, defaults included — pydantic serializes every
  // field, so a mock that returns only the interesting ones type-checks and
  // then diverges from the server.
  getBackupHealth: vi.fn(async () => ({
    enabled: true, running: true,
    last_attempt_at: null, last_success_at: null, last_success_derived: false,
    last_error: null, last_skip_reason: null, consecutive_failures: 0,
  })),
  backupDownloadUrl: vi.fn(() => '/api/admin/backup'),
  getBackupUpload: vi.fn<typeof S.getBackupUpload>(async () => ({
    configured: false, provider: null, destination: null, from_environment: false,
    // Providers are OBJECTS. This mock sent `['rclone']` (strings), so
    // `providers.find(p => p.name === provider)` never matched and the card's
    // `<option key={p.name}>` got `undefined` — a fiction tsc could not see
    // through an untyped `vi.fn(async () => ({…}))`.
    available_providers: [{
      name: 'rclone', label: 'rclone', destination_hint: 'remote:path',
      example: 'box:Headroom-Backups', setup: ['Install rclone'], secret_env: null,
      binary: 'rclone', binary_available: true,
    }],
    binary_available: null, last_upload_at: null, last_upload_ok: null,
    last_upload_error: null, last_upload_name: null, upload_successes: 0, upload_failures: 0,
  })),
  setBackupUpload: vi.fn(), clearBackupUpload: vi.fn(), testBackupUpload: vi.fn(),
  getActivityLog: vi.fn(async () => []),
  getRetentionStatus: vi.fn(async () => ({
    retention_days: 90,
    health: {
      name: 'retention prune', last_attempt_at: null, last_success_at: null,
      last_error: null, consecutive_failures: 0, last_result: 0,
    },
  })),
  getEbayCreds: vi.fn<typeof S.getEbayCreds>(async () => ({
    configured: false, app_id_masked: null, marketplace: 'EBAY_US', detected_env: null,
  })),
  setEbayCreds: vi.fn(), deleteEbayCreds: vi.fn(), testEbayCreds: vi.fn(),
  inventoryReportUrl: vi.fn(() => '/api/admin/inventory-report'),
  collectionExportUrl: vi.fn(() => '/api/admin/collection-export'),
  getColorwayStatus: vi.fn<typeof S.getColorwayStatus>(async () => ({
    entries: 988, models: 146, colorways: 402, last_harvest: null, in_flight: false,
    progress: sweepProgressFixture(),
  })),
  // Mock the real payload shape: pydantic serializes every field, defaults
  // included, so a partial literal is a fiction the component never receives.
  getRepricing: vi.fn<typeof S.getRepricing>(async () => ({
    enabled: true, interval_hours: 24, last_run_at: null, last_success_at: null,
    last_error: null, consecutive_failures: 0, last_repriced: 0, last_considered: 0,
    progress: sweepProgressFixture(),
  })),
  runRepricing: vi.fn(),
  // Deliberately NOT the mDNS host: the assertions below identify each card
  // by a value only that card's own query supplies, so two cards showing the
  // same string would make the check ambiguous rather than stronger.
  getTagBase: vi.fn(async () => ({
    base_url: 'http://tags.example:9000',
    source: 'settings',
    example_url: 'http://tags.example:9000/t/h/1',
  })),
  setTagBase: vi.fn(), clearTagBase: vi.fn(),
  getGuestView: vi.fn(async () => ({ enabled: false })),
  setGuestView: vi.fn(),
  auditConstructions: vi.fn(async () => [
    { construction: 'HYDROLite', hat_count: 12, priced_from_table: 9 },
  ]),
  clearConstruction: vi.fn(),
  auditFrozenPrices: vi.fn(async () => []),
  auditSharedPrices: vi.fn(async () => []),
  getUnclaimedFromPurchases: vi.fn(async () => (
    { colorways: 0, prices: 0, ambiguous: 0 })),
  releaseFrozenPrices: vi.fn(),
  runRepricingAll: vi.fn(),
  };
}

vi.mock('../api/auth', () => ({
  // The real payload: `/me` no longer carries `api_token`. Reading it is a
  // separate, password-gated request (S-07), so a mock that still returned the
  // token would be describing an endpoint that has stopped serving it.
  getMe: vi.fn(async () => ({ username: 'owner', token_set: true })),
  listPasskeys: vi.fn(async () => []),
  listShareLinks: vi.fn(async () => []),
  changePassword: vi.fn(), rotateApiToken: vi.fn(), revealApiToken: vi.fn(),
  deletePasskey: vi.fn(),
  passkeyRegisterOptions: vi.fn(), passkeyRegisterVerify: vi.fn(), logout: vi.fn(),
  createShareLink: vi.fn(), revokeShareLink: vi.fn(),
}));

// The CA-certificate probe must answer FALSE here: `TrustCertCard` renders only
// when a local CA exists, which is the LAN-HTTPS overlay only. (The probe is
// `caCertificateAvailable` in `api/settings`, mocked above; it is a plain
// `fetch`, not `apiFetch`, because the endpoint serves a PEM file.)
vi.mock('../api/client', () => ({
  apiFetch: vi.fn(async () => []),
  // Both exports, or a card reaching `api/hats` (which imports this one to
  // read `X-Total-Count`) gets `undefined` and fails on call rather than here.
  apiFetchWithHeaders: vi.fn(async () => ({ data: [], headers: new Headers() })),
}));
vi.mock('../lib/webauthn', () => ({
  createPasskey: vi.fn(), passkeysSupported: vi.fn(() => false),
}));

/**
 * Every card, by the section it lives in and in on-screen order within it.
 *
 * The page was one flat scroll of nineteen; it is now five sections and only
 * the active one is mounted. So the check is per-section rather than one list,
 * and the union below is what guarantees no card was dropped on the way — a
 * silent failure nothing else in the toolchain catches.
 */
const SECTION_CARDS: Record<string, string[]> = {
  analysis: [
    'Claude API Key',
    'Claude Model',
    'Google Vision Key (fallback)',
    'Analysis Queue',
    'Recent Analysis Errors',
  ],
  data: [
    'Construction audit',
    'Re-pricing',
    'Frozen prices',
    'Prices shared by many hats',
    'Colorway Catalog',
    'Purchase History',
    'eBay Comparable Listings (optional)',
  ],
  sharing: [
    'Guest browsing',
    'Share Links',
    'Share the collection',
    'Inventory Report',
    'Tags & labels',
    'Share Photos to Headroom',
  ],
  device: ['Account', 'LAN Discovery (mDNS)', 'Site Logo'],
  maintenance: ['Backups', 'Off-site backup', 'Recent Activity'],
};

/**
 * Cards that MOUNT but deliberately render nothing here.
 *
 * `TrustCertCard` shows only when a local CA exists, i.e. under the LAN-HTTPS
 * overlay, and the `apiFetch` mock above makes that probe fail on purpose.
 * Listed rather than omitted: while it was simply absent from the roster
 * above, the union check counted 21 against 22 mounted cards and deleting the
 * card from `SECTIONS` entirely kept the suite green. A conditional card still
 * has to be accounted for — it just is not accounted for by rendering.
 */
const MOUNTED_BUT_HIDDEN: Record<string, number> = { device: 1 };

/** Cards visible in a section, scoped to `.card-title` — card *bodies* mention
 *  other cards by name (ShareTargetCard points at "Account"), so a bare text
 *  query would be ambiguous. */
function renderedCards(container: HTMLElement): string[] {
  return [...container.querySelectorAll('.card-title')].map(el => el.textContent?.trim() ?? '');
}

beforeEach(() => { vi.clearAllMocks(); });

describe('SettingsPage', () => {
  it.each(Object.entries(SECTION_CARDS))(
    'renders the %s section, in the documented order',
    async (tab, expected) => {
      const { container } = renderWithProviders(<SettingsPage />, {
        route: `/settings?tab=${tab}`,
      });
      await screen.findByText(expected[0]);

      expect(renderedCards(container)).toEqual(expected);
    },
  );

  it('accounts for every card across the sections', () => {
    // Guards the real risk of splitting one list into five: a card that is in
    // no section renders nowhere and nothing else notices.
    //
    // Counted against the REAL section table, not a literal. This asserted
    // `toHaveLength(21)` beside a roster of 21 while SettingsPage mounted 22,
    // so `TrustCertCard` — the LAN-HTTPS "Trust this device" card — could be
    // deleted outright with every test still green. A census that restates a
    // number is a census of the number.
    const all = Object.values(SECTION_CARDS).flat();
    expect(new Set(all).size).toBe(all.length);

    const hidden = Object.values(MOUNTED_BUT_HIDDEN).reduce((a, b) => a + b, 0);
    const mounted = SECTIONS.flatMap(s => s.cards);
    expect(all.length + hidden).toBe(mounted.length);
    expect(Object.keys(SECTION_CARDS)).toHaveLength(SECTIONS.length);
    for (const section of SECTIONS) {
      const expected = section.cards.length - (MOUNTED_BUT_HIDDEN[section.id] ?? 0);
      expect(SECTION_CARDS[section.id]).toHaveLength(expected);
    }
  });

  it('defaults to the first section when no tab is named', async () => {
    const { container } = renderWithProviders(<SettingsPage />);
    await screen.findByText('Claude API Key');
    expect(renderedCards(container)).toEqual(SECTION_CARDS.analysis);
  });

  it('falls back to the first section when the tab is unknown', async () => {
    // `?tab=` comes from the URL, so it is whatever anyone types.
    const { container } = renderWithProviders(<SettingsPage />, {
      route: '/settings?tab=nonsense',
    });
    await screen.findByText('Claude API Key');
    expect(renderedCards(container)).toEqual(SECTION_CARDS.analysis);
  });

  it('switches section on tab press', async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<SettingsPage />);
    await screen.findByText('Claude API Key');

    await user.click(screen.getByRole('tab', { name: 'Upkeep' }));

    expect(renderedCards(container)).toEqual(SECTION_CARDS.maintenance);
  });

  it("surfaces data from each card's own query rather than a page-level fetch", async () => {
    renderWithProviders(<SettingsPage />, { route: '/settings?tab=analysis' });
    expect(await screen.findByText('sk-an…wxyz')).toBeInTheDocument();       // key card
    expect(await screen.findByText('claude-sonnet-5')).toBeInTheDocument(); // model card
  });

  it("surfaces each card's own query in the other sections too", async () => {
    renderWithProviders(<SettingsPage />, { route: '/settings?tab=device' });
    expect(await screen.findByText(/Signed in as/)).toBeInTheDocument();      // account card
    expect(await screen.findByText('http://headroom.local:8000')).toBeInTheDocument(); // mDNS
  });

  it('does not fetch for sections you are not looking at', async () => {
    // The point of mounting one section: the flat page fired every card's
    // query on open, most for cards you were never going to look at.
    const settingsApi = await import('../api/settings');
    renderWithProviders(<SettingsPage />, { route: '/settings?tab=maintenance' });
    await screen.findByText('Backups');

    expect(settingsApi.getApiKeyStatus).not.toHaveBeenCalled();
    expect(settingsApi.auditConstructions).not.toHaveBeenCalled();
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
    vi.mocked(settingsApi.getModel).mockResolvedValue({ model_id: 'claude-opus-5', source: 'database', default_model_id: 'claude-sonnet-5' });
    await client.invalidateQueries({ queryKey: ['settings', 'model'] });

    await waitFor(() => {
      expect(screen.queryByText(/Reachable\./)).not.toBeInTheDocument();
    });
  });
});

describe('ClaudeModelCard', () => {
  async function renderWithStoredModel(model_id: string) {
    vi.mocked(settingsApi.getModel).mockResolvedValue({ model_id, source: 'database', default_model_id: 'claude-sonnet-5' });
    renderWithProviders(<ClaudeModelCard />);
    await screen.findByText(model_id);
    return screen.getByLabelText('Model') as HTMLSelectElement;
  }

  it('keeps a superseded model on its own named option', async () => {
    // The whole reason legacy ids stay in the list. Dropping them would leave
    // an install that had saved one showing "Other…" with its id in a free-text
    // box — it still works, but it reads like the setting broke on upgrade.
    const select = await renderWithStoredModel('claude-sonnet-4-6');
    expect(select.value).toBe('claude-sonnet-4-6');
    expect(screen.queryByLabelText('Custom model ID')).not.toBeInTheDocument();
  });

  it('falls back to a custom-id box for a model it has never heard of', async () => {
    // Models ship faster than this app does, so an unrecognized id must stay
    // editable rather than being silently replaced by a listed one.
    const select = await renderWithStoredModel('claude-from-the-future-9');
    expect(select.value).toBe('__other__');
    expect(screen.getByLabelText('Custom model ID')).toHaveValue('claude-from-the-future-9');
  });
});
