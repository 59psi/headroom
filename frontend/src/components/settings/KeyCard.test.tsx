import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { AnthropicKeyCard } from './AnthropicKeyCard';
import { GoogleVisionKeyCard } from './GoogleVisionKeyCard';
import * as settingsApi from '../../api/settings';
import type { ApiKeyStatus } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getApiKeyStatus: vi.fn(),
    setApiKey: vi.fn(),
    deleteApiKey: vi.fn(),
    testApiKey: vi.fn(),
    getModel: vi.fn(async () => ({
      model_id: 'claude-sonnet-5', source: 'default', default_model_id: 'claude-sonnet-5',
    })),
    getGoogleVisionKeyStatus: vi.fn(),
    setGoogleVisionKey: vi.fn(),
    deleteGoogleVisionKey: vi.fn(),
  };
});

const NONE: ApiKeyStatus = { configured: false, source: null, masked: null };
const SAVED: ApiKeyStatus = { configured: true, source: 'database', masked: 'sk-an…wxyz' };
const FROM_ENV: ApiKeyStatus = { configured: true, source: 'environment', masked: 'sk-an…envv' };

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(settingsApi.getModel).mockResolvedValue({
    model_id: 'claude-sonnet-5', source: 'default', default_model_id: 'claude-sonnet-5',
  });
});

describe('Claude API key card — saving', () => {
  it('tests a new key straight after saving it, and reports once', async () => {
    // "Saved" alone answered the wrong question: a mistyped key saves as
    // happily as a good one, and the first sign was a hat failing later.
    const user = userEvent.setup();
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValueOnce(NONE).mockResolvedValue(SAVED);
    vi.mocked(settingsApi.setApiKey).mockResolvedValue(SAVED);
    vi.mocked(settingsApi.testApiKey).mockResolvedValue({ ok: true, detail: 'Reachable.' });

    renderWithProviders(<AnthropicKeyCard />);

    await user.type(await screen.findByLabelText('API key'), '  sk-ant-new  ');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    // Trimmed — pasted keys arrive with a trailing newline more often than not.
    expect(settingsApi.setApiKey).toHaveBeenCalledWith('sk-ant-new');
    expect(await screen.findByText('Key saved and working')).toBeInTheDocument();
    expect(settingsApi.testApiKey).toHaveBeenCalledTimes(1);
    expect(screen.getByText('sk-an…wxyz')).toBeInTheDocument();
    expect(screen.getByText('Connected')).toBeInTheDocument();
    // The field folds away once there is a key to show instead.
    expect(screen.queryByLabelText(/key$/i, { selector: 'input' })).not.toBeInTheDocument();
  });

  it('saves on Enter too', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue(NONE);
    vi.mocked(settingsApi.setApiKey).mockResolvedValue(SAVED);
    vi.mocked(settingsApi.testApiKey).mockResolvedValue({ ok: true, detail: 'Reachable.' });

    renderWithProviders(<AnthropicKeyCard />);
    await user.type(await screen.findByLabelText('API key'), 'sk-ant-new{Enter}');

    expect(settingsApi.setApiKey).toHaveBeenCalledWith('sk-ant-new');
  });

  it('keeps a failed test on the card and says so in the toast', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValueOnce(NONE).mockResolvedValue(SAVED);
    vi.mocked(settingsApi.setApiKey).mockResolvedValue(SAVED);
    vi.mocked(settingsApi.testApiKey).mockResolvedValue({ ok: false, detail: 'invalid x-api-key' });

    renderWithProviders(<AnthropicKeyCard />);
    await user.type(await screen.findByLabelText('API key'), 'sk-ant-typo');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    // The toast points; the card holds the detail, which does not time out.
    expect(await screen.findByText('Key saved, but the connection test failed')).toBeInTheDocument();
    expect(screen.getByText(/invalid x-api-key/)).toBeInTheDocument();
    expect(screen.getByText('Test failed')).toBeInTheDocument();
  });

  it('shows a rejected save in place and keeps what was typed', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue(NONE);
    vi.mocked(settingsApi.setApiKey).mockRejectedValue(new Error('Key is too short'));

    renderWithProviders(<AnthropicKeyCard />);
    const field = await screen.findByLabelText('API key');
    await user.type(field, 'sk');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Key is too short');
    expect(field).toHaveValue('sk');
    expect(settingsApi.testApiKey).not.toHaveBeenCalled();
  });

  it('folds the replacement field behind Replace while a key is set', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue(SAVED);

    renderWithProviders(<AnthropicKeyCard />);
    await screen.findByText('sk-an…wxyz');
    expect(document.getElementById('anthropic-key')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Replace' }));
    const field = screen.getByLabelText('Replacement key');
    expect(field).toHaveFocus();

    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(document.getElementById('anthropic-key')).toBeNull();
  });
});

describe('Claude API key card — removing', () => {
  it('asks first, and Cancel keeps the key', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue(SAVED);

    renderWithProviders(<AnthropicKeyCard />);
    await user.click(await screen.findByRole('button', { name: 'Remove key' }));

    const dialog = screen.getByRole('alertdialog', { name: 'Remove API key?' });
    expect(within(dialog).getByText(/fallback analysis only/)).toBeInTheDocument();
    // …unless the server has an environment key waiting behind the saved one,
    // which the resolver falls back to. The warning must not overclaim.
    expect(within(dialog).getByText('HEADROOM_ANTHROPIC_API_KEY')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(settingsApi.deleteApiKey).not.toHaveBeenCalled();
    expect(screen.getByText('sk-an…wxyz')).toBeInTheDocument();
  });

  it('removes once confirmed', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValueOnce(SAVED).mockResolvedValue(NONE);
    vi.mocked(settingsApi.deleteApiKey).mockResolvedValue(undefined);

    renderWithProviders(<AnthropicKeyCard />);
    await user.click(await screen.findByRole('button', { name: 'Remove key' }));
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Remove key' }));

    expect(settingsApi.deleteApiKey).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('Key removed')).toBeInTheDocument();
    expect(await screen.findByText('Not set')).toBeInTheDocument();
  });

  it('offers no Remove for a key from the environment, and names where it lives', async () => {
    // DELETE clears the DATABASE value only. For an environment key the
    // button did nothing and said nothing; the card now says where to go.
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue(FROM_ENV);

    renderWithProviders(<AnthropicKeyCard />);
    await screen.findByText('sk-an…envv');

    expect(screen.queryByRole('button', { name: 'Remove key' })).not.toBeInTheDocument();
    expect(screen.getByText('HEADROOM_ANTHROPIC_API_KEY', { selector: '.hr-an-note code' })).toBeInTheDocument();
    // Replacing is still possible: a key saved here takes precedence.
    expect(screen.getByRole('button', { name: 'Replace' })).toBeInTheDocument();
  });
});

describe('Google Vision key card', () => {
  it('reads as optional when unset, with no test to run', async () => {
    vi.mocked(settingsApi.getGoogleVisionKeyStatus).mockResolvedValue(NONE);

    renderWithProviders(<GoogleVisionKeyCard />);

    expect(await screen.findByText('No key configured — fallback provides colors only.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Google Vision key' })).toBeInTheDocument();
    expect(screen.getByText(/Optional fallback/)).toBeInTheDocument();
    expect(screen.getByText('Not set')).toBeInTheDocument();
  });

  it('saves with a plain acknowledgment — there is no cheap probe to run', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getGoogleVisionKeyStatus)
      .mockResolvedValueOnce(NONE)
      .mockResolvedValue({ configured: true, source: 'database', masked: 'AIzaS…1234' });
    vi.mocked(settingsApi.setGoogleVisionKey).mockResolvedValue({
      configured: true, source: 'database', masked: 'AIzaS…1234',
    });

    renderWithProviders(<GoogleVisionKeyCard />);
    await user.type(await screen.findByLabelText('API key'), 'AIzaSy-new');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Key saved')).toBeInTheDocument();
    expect(settingsApi.testApiKey).not.toHaveBeenCalled();
    expect(await screen.findByText('AIzaS…1234')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /test connection/i })).not.toBeInTheDocument();
  });
});
