import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { EbayCredsCard } from './EbayCredsCard';
import * as api from '../../api/settings';
import type { EbayCredsStatus } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getEbayCreds: vi.fn(),
    setEbayCreds: vi.fn(),
    deleteEbayCreds: vi.fn(),
    testEbayCreds: vi.fn(),
  };
});

const mocked = vi.mocked(api);

function creds(over: Partial<EbayCredsStatus> = {}): EbayCredsStatus {
  return {
    configured: false, app_id_masked: null, marketplace: 'EBAY_US', detected_env: null,
    ...over,
  };
}

const CONNECTED = creds({
  configured: true, app_id_masked: 'Brand…PRD-1a2b', detected_env: 'production',
});

beforeEach(() => { vi.clearAllMocks(); });

describe('EbayCredsCard — state', () => {
  it('says it is optional and not set, once it knows', async () => {
    mocked.getEbayCreds.mockResolvedValue(creds());
    renderWithProviders(<EbayCredsCard />);

    expect(await screen.findByText('Not set')).toBeInTheDocument();
    expect(screen.getByText(/^Optional\./)).toBeInTheDocument();
    expect(screen.getByText(/search deep-link only, no live prices/)).toBeInTheDocument();
  });

  it('never claims "Not set" while the status is still loading', async () => {
    // A configured install must not flash the unconfigured answer first.
    mocked.getEbayCreds.mockReturnValue(new Promise<EbayCredsStatus>(() => {}));
    renderWithProviders(<EbayCredsCard />);

    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(screen.queryByText('Not set')).toBeNull();
    expect(screen.queryByText(/search deep-link only/)).toBeNull();
  });

  it('shows the active keyset and its environment when connected', async () => {
    mocked.getEbayCreds.mockResolvedValue(CONNECTED);
    renderWithProviders(<EbayCredsCard />);

    // Configured, not "Connected": a saved keyset says nothing about whether
    // it connects until a test has passed.
    expect(await screen.findByText('Configured')).toBeInTheDocument();
    expect(screen.queryByText('Connected')).toBeNull();
    expect(screen.getByText('Brand…PRD-1a2b')).toBeInTheDocument();
    // The pill, not the word "Production" in the setup instructions.
    expect(screen.getByText('Production', { selector: '.hr-pill' })).toBeInTheDocument();
  });

  it('flags a sandbox keyset, which fails every call with a 401', async () => {
    mocked.getEbayCreds.mockResolvedValue(creds({
      configured: true, app_id_masked: 'Brand…SBX-9z', detected_env: 'sandbox',
    }));
    renderWithProviders(<EbayCredsCard />);

    expect(await screen.findByText('Sandbox')).toBeInTheDocument();
    // Known bad before any test, so the header says so rather than "Configured".
    expect(screen.getByText('Sandbox keys', { selector: '.hr-pill' })).toBeInTheDocument();
    expect(screen.getByText(/they will fail with a 401/)).toBeInTheDocument();
  });
});

describe('EbayCredsCard — save', () => {
  it('saves trimmed values and flips to Configured from the reply, not a refetch', async () => {
    const user = userEvent.setup();
    // First read: nothing configured. Every read after that hangs, so the only
    // way the card can show "Configured" is from the PUT's own answer.
    mocked.getEbayCreds
      .mockResolvedValueOnce(creds())
      .mockReturnValue(new Promise<EbayCredsStatus>(() => {}));
    mocked.setEbayCreds.mockResolvedValue(CONNECTED);

    renderWithProviders(<EbayCredsCard />);
    await screen.findByText('Not set');

    const save = screen.getByRole('button', { name: 'Save credentials' });
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText('App ID (Client ID)'), '  Brand-app-PRD  ');
    await user.type(screen.getByLabelText('Cert ID (Client Secret)'), 'PRD-secret');
    await user.click(save);

    expect(mocked.setEbayCreds).toHaveBeenCalledWith({ app_id: 'Brand-app-PRD', cert_id: 'PRD-secret' });
    expect(await screen.findByText('Configured')).toBeInTheDocument();
    expect(screen.getByText('eBay credentials saved')).toBeInTheDocument();
    // The secret does not linger in the box after it has been sent.
    expect(screen.getByLabelText('Cert ID (Client Secret)')).toHaveValue('');
  });

  it('is a real form, so Return in a field submits it', async () => {
    // The Save button lives in the card footer, outside the <form>, tied to it
    // by the `form` attribute — which browsers honor for implicit submission
    // (the default button is any submit button whose form OWNER is the form).
    // user-event only looks for a submit button INSIDE the form, so this
    // dispatches the submit that Return produces rather than typing it.
    const user = userEvent.setup();
    mocked.getEbayCreds.mockResolvedValue(creds());
    mocked.setEbayCreds.mockResolvedValue(CONNECTED);
    renderWithProviders(<EbayCredsCard />);
    await screen.findByText('Not set');

    const cert = screen.getByLabelText('Cert ID (Client Secret)');
    // Half-filled: submitting sends nothing.
    await user.type(cert, 'cert');
    fireEvent.submit(cert.closest('form')!);
    expect(mocked.setEbayCreds).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText('App ID (Client ID)'), 'app');
    expect(screen.getByRole('button', { name: 'Save credentials' }))
      .toHaveAttribute('form', cert.closest('form')!.id);
    fireEvent.submit(cert.closest('form')!);

    await waitFor(() =>
      expect(mocked.setEbayCreds).toHaveBeenCalledWith({ app_id: 'app', cert_id: 'cert' }));
  });
});

describe('EbayCredsCard — remove asks first, in-app', () => {
  it('removes nothing when the dialog is canceled', async () => {
    const user = userEvent.setup();
    mocked.getEbayCreds.mockResolvedValue(CONNECTED);
    renderWithProviders(<EbayCredsCard />);

    await user.click(await screen.findByRole('button', { name: 'Remove' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Remove eBay credentials?' });
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(mocked.deleteEbayCreds).not.toHaveBeenCalled();
  });

  it('removes on confirm and says so', async () => {
    const user = userEvent.setup();
    mocked.getEbayCreds.mockResolvedValue(CONNECTED);
    mocked.deleteEbayCreds.mockResolvedValue(undefined);
    renderWithProviders(<EbayCredsCard />);

    await user.click(await screen.findByRole('button', { name: 'Remove' }));
    expect(mocked.deleteEbayCreds).not.toHaveBeenCalled();
    const dialog = await screen.findByRole('alertdialog', { name: 'Remove eBay credentials?' });
    await user.click(within(dialog).getByRole('button', { name: 'Remove credentials' }));

    await waitFor(() => expect(mocked.deleteEbayCreds).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('eBay credentials removed')).toBeInTheDocument();
  });
});

describe('EbayCredsCard — test connection', () => {
  it('reports where a failing keyset broke', async () => {
    const user = userEvent.setup();
    mocked.getEbayCreds.mockResolvedValue(CONNECTED);
    mocked.testEbayCreds.mockResolvedValue({ ok: false, stage: 'oauth', detail: '401 invalid_client' });
    renderWithProviders(<EbayCredsCard />);

    await user.click(await screen.findByRole('button', { name: 'Test connection' }));

    expect(await screen.findByText(/401 invalid_client/)).toBeInTheDocument();
    expect(screen.getByText('oauth')).toBeInTheDocument();
    expect(screen.getByText('Failing', { selector: '.hr-pill' })).toBeInTheDocument();
  });

  it('earns "Connected" only from a passing test', async () => {
    const user = userEvent.setup();
    mocked.getEbayCreds.mockResolvedValue(CONNECTED);
    mocked.testEbayCreds.mockResolvedValue({ ok: true, stage: 'search', detail: 'Reachable — 12 listings' });
    renderWithProviders(<EbayCredsCard />);

    await screen.findByText('Configured');
    await user.click(screen.getByRole('button', { name: 'Test connection' }));

    expect(await screen.findByText('Connected', { selector: '.hr-pill' })).toBeInTheDocument();
    expect(screen.queryByText('Configured')).toBeNull();
  });
});
