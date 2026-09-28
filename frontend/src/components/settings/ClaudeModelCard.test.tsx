import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { ClaudeModelCard } from './ClaudeModelCard';
import * as settingsApi from '../../api/settings';
import type { ModelStatus } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getModel: vi.fn(),
    setModel: vi.fn(),
    clearModel: vi.fn(),
    getApiKeyStatus: vi.fn(),
    testApiKey: vi.fn(),
  };
});

const SONNET: ModelStatus = { model_id: 'claude-sonnet-5', source: 'default', default_model_id: 'claude-sonnet-5' };
const OPUS: ModelStatus = { model_id: 'claude-opus-5', source: 'database', default_model_id: 'claude-sonnet-5' };

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue({
    configured: true, source: 'database', masked: 'sk-an…wxyz',
  });
  vi.mocked(settingsApi.testApiKey).mockResolvedValue({ ok: true, detail: 'Reachable.' });
});

async function renderCard() {
  const view = renderWithProviders(<ClaudeModelCard />);
  await screen.findByText(/^claude-/, { selector: 'code' });
  return { ...view, select: screen.getByLabelText('Model') as HTMLSelectElement };
}

describe('ClaudeModelCard — picking a model', () => {
  it('saves the moment a model is picked, with no Save button in the way', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(SONNET).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.setModel).mockResolvedValue(OPUS);

    const { select } = await renderCard();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();

    await user.selectOptions(select, 'claude-opus-5');

    expect(settingsApi.setModel).toHaveBeenCalledWith('claude-opus-5');
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    expect(select.value).toBe('claude-opus-5');
  });

  it('checks the new model against the API straight after saving', async () => {
    // The card used to end with "test the connection above after changing" —
    // a step everyone skips, so a bad id surfaced as the next photo failing.
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(SONNET).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.setModel).mockResolvedValue(OPUS);

    const { select } = await renderCard();
    await user.selectOptions(select, 'claude-opus-5');

    expect(await screen.findByText(/Reachable\./)).toBeInTheDocument();
    expect(settingsApi.testApiKey).toHaveBeenCalledTimes(1);
  });

  it('says "Connected" only after Claude answers with the model, and "Failing" when it refuses', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(SONNET).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.setModel).mockResolvedValue(OPUS);

    const { select } = await renderCard();
    // Before any check the pill can only say where the choice came from.
    expect(screen.getByText('Default', { selector: '.hr-pill' })).toBeInTheDocument();
    expect(screen.queryByText('Connected')).not.toBeInTheDocument();

    await user.selectOptions(select, 'claude-opus-5');
    expect(await screen.findByText('Connected', { selector: '.hr-pill' })).toBeInTheDocument();
  });

  it('reads "Failing" when the check against the new model is refused', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(SONNET).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.setModel).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.testApiKey).mockResolvedValue({ ok: false, detail: 'model not found' });

    const { select } = await renderCard();
    await user.selectOptions(select, 'claude-opus-5');

    expect(await screen.findByText('Failing', { selector: '.hr-pill' })).toBeInTheDocument();
  });

  it('does not call Haiku the cheapest — its cache minimum is longer than the prompt', async () => {
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    await renderCard();
    const haiku = screen.getByRole('option', { name: /Haiku 4\.5/ });
    expect(haiku).not.toHaveTextContent(/cheapest/);
    expect(haiku).toHaveTextContent(/too short to cache/);
  });

  it('does not run the check with no key to run it with', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue({ configured: false, source: null, masked: null });
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(SONNET).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.setModel).mockResolvedValue(OPUS);

    const { select } = await renderCard();
    await user.selectOptions(select, 'claude-opus-5');

    expect(await screen.findByText('Saved')).toBeInTheDocument();
    expect(settingsApi.testApiKey).not.toHaveBeenCalled();
  });

  it('shows the pick at once and rolls it back if the server refuses', async () => {
    const user = userEvent.setup();
    let reject!: (e: Error) => void;
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    vi.mocked(settingsApi.setModel).mockReturnValue(
      new Promise<ModelStatus>((_, r) => { reject = r; }),
    );

    const { select } = await renderCard();
    await user.selectOptions(select, 'claude-opus-5');

    // Optimistic: the picker and the active id move before the server answers.
    expect(select.value).toBe('claude-opus-5');
    expect(screen.getByText('claude-opus-5', { selector: 'code' })).toBeInTheDocument();
    expect(screen.getByText('Saving…')).toBeInTheDocument();

    reject(new Error('Model id not allowed'));

    // …and back to what the server still has, with the reason in place.
    await waitFor(() => expect(select.value).toBe('claude-sonnet-5'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Model id not allowed');
    expect(screen.getByText('Not saved')).toBeInTheDocument();
    expect(settingsApi.testApiKey).not.toHaveBeenCalled();
  });

  it('keeps the latest pick on screen while an earlier one is still saving', async () => {
    // Two quick picks (arrow keys on a focused select fire one change per
    // option). The first save answering must not flick the picker back to a
    // model the person has already moved past, nor spend a check on it.
    const user = userEvent.setup();
    const HAIKU: ModelStatus = { ...OPUS, model_id: 'claude-haiku-4-5-20251001' };
    let finishOpus!: (s: ModelStatus) => void;
    let finishHaiku!: (s: ModelStatus) => void;
    // What a GET would answer at each moment: Opus once its save has landed,
    // Haiku only once the second one has.
    let server = SONNET;
    vi.mocked(settingsApi.getModel).mockImplementation(async () => server);
    vi.mocked(settingsApi.setModel)
      .mockReturnValueOnce(new Promise<ModelStatus>(r => { finishOpus = r; }))
      .mockReturnValueOnce(new Promise<ModelStatus>(r => { finishHaiku = r; }));

    const { select } = await renderCard();
    await user.selectOptions(select, 'claude-opus-5');
    await user.selectOptions(select, 'claude-haiku-4-5-20251001');
    expect(select.value).toBe('claude-haiku-4-5-20251001');

    server = OPUS;
    finishOpus(OPUS);
    // The second save starts only once the first is done (one writer at a time).
    await waitFor(() => expect(settingsApi.setModel).toHaveBeenCalledTimes(2));
    // Give any stray cache write or refetch a chance to land.
    await new Promise(r => setTimeout(r, 20));
    expect(select.value).toBe('claude-haiku-4-5-20251001');
    expect(settingsApi.testApiKey).not.toHaveBeenCalled();

    server = HAIKU;
    finishHaiku(HAIKU);
    expect(await screen.findByText(/Reachable\./)).toBeInTheDocument();
    expect(select.value).toBe('claude-haiku-4-5-20251001');
    expect(settingsApi.setModel).toHaveBeenNthCalledWith(1, 'claude-opus-5');
    expect(settingsApi.setModel).toHaveBeenNthCalledWith(2, 'claude-haiku-4-5-20251001');
    expect(settingsApi.testApiKey).toHaveBeenCalledTimes(1);
  });

  it("keeps the latest model's check when an older one answers last", async () => {
    // Each save finished before the next pick, so each got its own check —
    // and a check is a real round trip to Anthropic, so they can answer out
    // of order. The late answer about Opus must not wipe the one about Haiku.
    const user = userEvent.setup();
    const HAIKU: ModelStatus = { ...OPUS, model_id: 'claude-haiku-4-5-20251001' };
    let server = SONNET;
    vi.mocked(settingsApi.getModel).mockImplementation(async () => server);
    vi.mocked(settingsApi.setModel).mockImplementation(async id => {
      server = id === OPUS.model_id ? OPUS : HAIKU;
      return server;
    });
    let answerOpus!: (r: { ok: boolean; detail: string }) => void;
    let answerHaiku!: (r: { ok: boolean; detail: string }) => void;
    vi.mocked(settingsApi.testApiKey)
      .mockReturnValueOnce(new Promise(r => { answerOpus = r; }))
      .mockReturnValueOnce(new Promise(r => { answerHaiku = r; }));

    const { select } = await renderCard();
    await user.selectOptions(select, 'claude-opus-5');
    await waitFor(() => expect(settingsApi.testApiKey).toHaveBeenCalledTimes(1));
    await user.selectOptions(select, 'claude-haiku-4-5-20251001');
    await waitFor(() => expect(settingsApi.testApiKey).toHaveBeenCalledTimes(2));

    answerHaiku({ ok: true, detail: 'Haiku answers.' });
    expect(await screen.findByText(/Haiku answers\./)).toBeInTheDocument();

    answerOpus({ ok: true, detail: 'Opus answers.' });
    await new Promise(r => setTimeout(r, 20));
    expect(screen.getByText(/Haiku answers\./)).toBeInTheDocument();
    expect(screen.queryByText(/Opus answers\./)).not.toBeInTheDocument();
  });
});

describe('ClaudeModelCard — a custom model id', () => {
  it('waits for Enter rather than saving every keystroke', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    vi.mocked(settingsApi.setModel).mockResolvedValue({ ...OPUS, model_id: 'claude-next-1' });

    const { select } = await renderCard();
    await user.selectOptions(select, '__other__');

    const field = screen.getByLabelText('Custom model ID');
    // Opened by the person, so it takes focus — and starts empty, not holding
    // the listed model it replaced.
    expect(field).toHaveFocus();
    expect(field).toHaveValue('');
    // Picking "Other…" saves nothing by itself.
    expect(settingsApi.setModel).not.toHaveBeenCalled();

    await user.type(field, 'claude-next-1');
    expect(settingsApi.setModel).not.toHaveBeenCalled();

    await user.keyboard('{Enter}');
    expect(settingsApi.setModel).toHaveBeenCalledTimes(1);
    expect(settingsApi.setModel).toHaveBeenCalledWith('claude-next-1');
  });

  it('will not save the id already in use', async () => {
    vi.mocked(settingsApi.getModel).mockResolvedValue({ ...OPUS, model_id: 'claude-from-the-future-9' });
    await renderCard();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });
});

describe('ClaudeModelCard — reset to default', () => {
  it('is offered only for a model chosen here', async () => {
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    await renderCard();
    expect(screen.queryByRole('button', { name: 'Reset to default' })).not.toBeInTheDocument();
    expect(screen.getByText('Default')).toBeInTheDocument();
  });

  it('asks first, and Cancel changes nothing', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValue(OPUS);

    await renderCard();
    await user.click(screen.getByRole('button', { name: 'Reset to default' }));
    const dialog = screen.getByRole('dialog', { name: 'Reset to default?' });
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));

    expect(settingsApi.clearModel).not.toHaveBeenCalled();
  });

  it('resets once confirmed and says so', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(OPUS).mockResolvedValue(SONNET);
    vi.mocked(settingsApi.clearModel).mockResolvedValue(undefined);

    const { select } = await renderCard();
    await user.click(screen.getByRole('button', { name: 'Reset to default' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Reset to default' }));

    expect(settingsApi.clearModel).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('Model reset to default')).toBeInTheDocument();
    await waitFor(() => expect(select.value).toBe('claude-sonnet-5'));
  });
});
