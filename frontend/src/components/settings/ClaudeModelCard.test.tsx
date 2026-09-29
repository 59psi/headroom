import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { formatDateOnly } from '../../lib/dates';
import { ClaudeModelCard } from './ClaudeModelCard';
import * as settingsApi from '../../api/settings';
import type { ModelOption, ModelOptions, ModelStatus } from '../../types';

vi.mock('../../api/settings', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getModel: vi.fn(),
    getModelOptions: vi.fn(),
    setModel: vi.fn(),
    clearModel: vi.fn(),
    getApiKeyStatus: vi.fn(),
    testApiKey: vi.fn(),
  };
});

/** One list entry, every field present — pydantic serializes them all, so a
 *  fixture missing one would describe a payload the card is never handed. */
function entry(fields: Pick<ModelOption, 'id' | 'name' | 'status'> & Partial<ModelOption>): ModelOption {
  return {
    speed: null, cost_level: null, summary: null, note: null, successor: null,
    forced_tool: false, available: true, retires_after: null,
    ...fields,
  };
}

const FABLE_5_1 = entry({
  id: 'claude-fable-5-1', name: 'Claude Fable 5.1', status: 'current',
  speed: 'Slower', cost_level: 5, summary: 'most capable, priciest',
});
const OPUS_5_5 = entry({
  id: 'claude-opus-5-5', name: 'Claude Opus 5.5', status: 'current',
  speed: 'Moderate', cost_level: 3, summary: 'finer model names, slower',
});
const SONNET_5_5 = entry({
  id: 'claude-sonnet-5-5', name: 'Claude Sonnet 5.5', status: 'current',
  speed: 'Fast', cost_level: 2, summary: 'fast and inexpensive',
});
const HAIKU_4_5 = entry({
  id: 'claude-haiku-4-5', name: 'Claude Haiku 4.5', status: 'current',
  speed: 'Fastest', cost_level: 1, summary: 'cheapest per token, no caching', forced_tool: true,
  note: 'Its cache minimum is longer than this prompt, so no analysis is cached.',
  retires_after: '2026-10-15',
});
const OPUS_5 = entry({
  id: 'claude-opus-5', name: 'Claude Opus 5', status: 'legacy',
  successor: 'claude-opus-5-5', forced_tool: true,
});
const SONNET_4_6 = entry({
  id: 'claude-sonnet-4-6', name: 'Claude Sonnet 4.6', status: 'legacy',
  successor: 'claude-sonnet-5-5', forced_tool: true,
});
const OPUS_4_1 = entry({
  id: 'claude-opus-4-1', name: 'Claude Opus 4.1', status: 'retired',
  successor: 'claude-opus-5-5', forced_tool: true, available: false,
});

const LIST: ModelOptions = {
  default_model_id: 'claude-sonnet-5-5',
  live: true,
  checked_at: new Date().toISOString(),
  live_error: null,
  models: [FABLE_5_1, OPUS_5_5, SONNET_5_5, HAIKU_4_5, OPUS_5, SONNET_4_6, OPUS_4_1],
};

const SONNET: ModelStatus = { model_id: 'claude-sonnet-5-5', source: 'default', default_model_id: 'claude-sonnet-5-5' };
const OPUS: ModelStatus = { model_id: 'claude-opus-5-5', source: 'database', default_model_id: 'claude-sonnet-5-5' };
const HAIKU: ModelStatus = { ...OPUS, model_id: 'claude-haiku-4-5' };
const saved = (model_id: string): ModelStatus => ({ ...OPUS, model_id });

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue({
    configured: true, source: 'database', masked: 'sk-an…wxyz',
  });
  vi.mocked(settingsApi.testApiKey).mockResolvedValue({ ok: true, detail: 'Reachable.' });
  vi.mocked(settingsApi.getModelOptions).mockResolvedValue(LIST);
});

async function renderCard() {
  const view = renderWithProviders(<ClaudeModelCard />);
  await screen.findByText(/^claude-/, { selector: 'code' });
  // The picker waits for its list; the rest of the card does not, so the
  // saved model can be on screen a render before the select is.
  return { ...view, select: await screen.findByLabelText('Model') as HTMLSelectElement };
}

/** The option labels under one optgroup, in order. */
function group(select: HTMLSelectElement, label: string): string[] {
  const g = select.querySelector(`optgroup[label="${label}"]`);
  return g ? [...g.querySelectorAll('option')].map(o => o.textContent ?? '') : [];
}

describe('ClaudeModelCard — picking a model', () => {
  it('saves the moment a model is picked, with no Save button in the way', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(SONNET).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.setModel).mockResolvedValue(OPUS);

    const { select } = await renderCard();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();

    await user.selectOptions(select, 'claude-opus-5-5');

    expect(settingsApi.setModel).toHaveBeenCalledWith('claude-opus-5-5');
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    expect(select.value).toBe('claude-opus-5-5');
  });

  it('refetches the list once the save lands — its ids follow the saved model', async () => {
    // The server shows an entry under the spelling this install saved, so a
    // list fetched before the save can carry the old spelling.
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(SONNET).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.setModel).mockResolvedValue(OPUS);

    const { select } = await renderCard();
    expect(settingsApi.getModelOptions).toHaveBeenCalledTimes(1);
    await user.selectOptions(select, 'claude-opus-5-5');

    await waitFor(() => expect(settingsApi.getModelOptions).toHaveBeenCalledTimes(2));
    // The ordinary read, not a forced check with Anthropic.
    expect(settingsApi.getModelOptions).toHaveBeenLastCalledWith();
  });

  it('checks the new model against the API straight after saving', async () => {
    // The card used to end with "test the connection above after changing" —
    // a step everyone skips, so a bad id surfaced as the next photo failing.
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(SONNET).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.setModel).mockResolvedValue(OPUS);

    const { select } = await renderCard();
    await user.selectOptions(select, 'claude-opus-5-5');

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

    await user.selectOptions(select, 'claude-opus-5-5');
    expect(await screen.findByText('Connected', { selector: '.hr-pill' })).toBeInTheDocument();
  });

  it('reads "Failing" when the check against the new model is refused', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(SONNET).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.setModel).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.testApiKey).mockResolvedValue({ ok: false, detail: 'model not found' });

    const { select } = await renderCard();
    await user.selectOptions(select, 'claude-opus-5-5');

    expect(await screen.findByText('Failing', { selector: '.hr-pill' })).toBeInTheDocument();
  });

  it('does not run the check with no key to run it with', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getApiKeyStatus).mockResolvedValue({ configured: false, source: null, masked: null });
    vi.mocked(settingsApi.getModel).mockResolvedValueOnce(SONNET).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.setModel).mockResolvedValue(OPUS);

    const { select } = await renderCard();
    await user.selectOptions(select, 'claude-opus-5-5');

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
    await user.selectOptions(select, 'claude-opus-5-5');

    // Optimistic: the picker and the active id move before the server answers.
    expect(select.value).toBe('claude-opus-5-5');
    expect(screen.getByText('claude-opus-5-5', { selector: 'code' })).toBeInTheDocument();
    expect(screen.getByText('Saving…')).toBeInTheDocument();

    // The refetch after the failure is held, so what puts the picker back is
    // the rollback itself — an answering refetch masked its absence. (The
    // save settles, error and all, only once that refetch lands.)
    let refetched!: (s: ModelStatus) => void;
    vi.mocked(settingsApi.getModel).mockReturnValue(new Promise<ModelStatus>(r => { refetched = r; }));
    reject(new Error('Model id not allowed'));

    // …and back to what the server still has, with the reason in place.
    await waitFor(() => expect(select.value).toBe('claude-sonnet-5-5'));
    refetched(SONNET);
    expect(await screen.findByRole('alert')).toHaveTextContent('Model id not allowed');
    expect(screen.getByText('Not saved')).toBeInTheDocument();
    expect(settingsApi.testApiKey).not.toHaveBeenCalled();
  });

  it('keeps the latest pick on screen while an earlier one is still saving', async () => {
    // Two quick picks (arrow keys on a focused select fire one change per
    // option). The first save answering must not flick the picker back to a
    // model the person has already moved past, nor spend a check on it.
    const user = userEvent.setup();
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
    await user.selectOptions(select, 'claude-opus-5-5');
    await user.selectOptions(select, 'claude-haiku-4-5');
    expect(select.value).toBe('claude-haiku-4-5');

    server = OPUS;
    finishOpus(OPUS);
    // The second save starts only once the first is done (one writer at a time).
    await waitFor(() => expect(settingsApi.setModel).toHaveBeenCalledTimes(2));
    // Give any stray cache write or refetch a chance to land.
    await new Promise(r => setTimeout(r, 20));
    expect(select.value).toBe('claude-haiku-4-5');
    expect(settingsApi.testApiKey).not.toHaveBeenCalled();

    server = HAIKU;
    finishHaiku(HAIKU);
    expect(await screen.findByText(/Reachable\./)).toBeInTheDocument();
    expect(select.value).toBe('claude-haiku-4-5');
    expect(settingsApi.setModel).toHaveBeenNthCalledWith(1, 'claude-opus-5-5');
    expect(settingsApi.setModel).toHaveBeenNthCalledWith(2, 'claude-haiku-4-5');
    expect(settingsApi.testApiKey).toHaveBeenCalledTimes(1);
  });

  it("keeps the latest model's check when an older one answers last", async () => {
    // Each save finished before the next pick, so each got its own check —
    // and a check is a real round trip to Anthropic, so they can answer out
    // of order. The late answer about Opus must not wipe the one about Haiku.
    const user = userEvent.setup();
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
    await user.selectOptions(select, 'claude-opus-5-5');
    await waitFor(() => expect(settingsApi.testApiKey).toHaveBeenCalledTimes(1));
    await user.selectOptions(select, 'claude-haiku-4-5');
    await waitFor(() => expect(settingsApi.testApiKey).toHaveBeenCalledTimes(2));

    answerHaiku({ ok: true, detail: 'Haiku answers.' });
    expect(await screen.findByText(/Haiku answers\./)).toBeInTheDocument();

    answerOpus({ ok: true, detail: 'Opus answers.' });
    await new Promise(r => setTimeout(r, 20));
    expect(screen.getByText(/Haiku answers\./)).toBeInTheDocument();
    expect(screen.queryByText(/Opus answers\./)).not.toBeInTheDocument();
  });
});

describe('ClaudeModelCard — the list', () => {
  it('groups current models apart from the previous generation, and marks the default', async () => {
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    const { select } = await renderCard();

    // The server's order within each group; "Claude " dropped from every
    // label, since every option is one and the closed face is 390 px wide.
    expect(group(select, 'Current models')).toEqual([
      'Fable 5.1 — most capable, priciest',
      'Opus 5.5 — finer model names, slower',
      'Sonnet 5.5 — fast and inexpensive (default)',
      'Haiku 4.5 — cheapest per token, no caching',
    ]);
    expect(group(select, 'Previous generation')).toEqual(['Opus 5', 'Sonnet 4.6']);
    expect(screen.getByRole('option', { name: 'Other (enter custom ID)…' })).toBeInTheDocument();
  });

  it('lists a retired model only while it is the saved one, and says so', async () => {
    // Offering every retired id invites picking one; dropping the saved one
    // would leave the picker on "Other…" with no word about why.
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    const first = await renderCard();
    expect(screen.queryByRole('option', { name: /Opus 4\.1/ })).not.toBeInTheDocument();
    first.unmount();

    vi.mocked(settingsApi.getModel).mockResolvedValue(saved('claude-opus-4-1'));
    const { select } = await renderCard();
    expect(select.value).toBe('claude-opus-4-1');
    expect(group(select, 'Previous generation')).toContain('Opus 4.1 (retired)');
    expect(screen.queryByLabelText('Custom model ID')).not.toBeInTheDocument();
  });

  it('offers a model Anthropic lists that this build has never heard of', async () => {
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    vi.mocked(settingsApi.getModelOptions).mockResolvedValue({
      ...LIST,
      models: [
        entry({ id: 'claude-sonnet-6', name: 'Claude Sonnet 6', status: 'new', available: true }),
        ...LIST.models,
      ],
    });
    const { select } = await renderCard();

    // After the catalog's current models, not ahead of them: the known ones
    // come with a summary and a speed, the new one only with its name.
    const current = group(select, 'Current models');
    expect(current[current.length - 1]).toBe('Sonnet 6 — new');
    expect(current).toHaveLength(5);
  });

  it('keeps a dated id saved by an older build on its named option', async () => {
    // This card's previous list offered Haiku 4.5 by its dated id; the list
    // now carries it once, under its alias. The install that saved the
    // dated one must not open on "Other…" as if the setting had broken.
    vi.mocked(settingsApi.getModel).mockResolvedValue(saved('claude-haiku-4-5-20251001'));
    const { select } = await renderCard();

    expect(select.value).toBe('claude-haiku-4-5');
    expect(screen.queryByLabelText('Custom model ID')).not.toBeInTheDocument();
    expect(screen.getByText('claude-haiku-4-5-20251001', { selector: 'code' })).toBeInTheDocument();
  });

  it('treats re-picking the entry a dated id sits on as no change', async () => {
    // Into "Other…" and back out onto the same model: nothing to save, and
    // no check to spend — the two ids are one model.
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValue(saved('claude-haiku-4-5-20251001'));
    const { select } = await renderCard();

    await user.selectOptions(select, '__other__');
    await user.selectOptions(select, 'claude-haiku-4-5');

    expect(select.value).toBe('claude-haiku-4-5');
    expect(settingsApi.setModel).not.toHaveBeenCalled();
  });

  it('will not guess between two models that share a base id', async () => {
    // The two dated Claude 3.5 Sonnets are different models; an alias that
    // could be either is left in the custom box rather than pinned to one.
    vi.mocked(settingsApi.getModel).mockResolvedValue(saved('claude-3-5-sonnet-latest'));
    vi.mocked(settingsApi.getModelOptions).mockResolvedValue({
      ...LIST,
      models: [
        ...LIST.models,
        entry({ id: 'claude-3-5-sonnet-20241022', name: 'Claude Sonnet 3.5 (Oct)', status: 'retired', available: false }),
        entry({ id: 'claude-3-5-sonnet-20240620', name: 'Claude Sonnet 3.5 (Jun)', status: 'retired', available: false }),
      ],
    });
    const { select } = await renderCard();

    expect(select.value).toBe('__other__');
    expect(screen.getByLabelText('Custom model ID')).toHaveValue('claude-3-5-sonnet-latest');
  });

  it("shows the picked model's speed, relative cost, note and retirement date", async () => {
    vi.mocked(settingsApi.getModel).mockResolvedValue(HAIKU);
    await renderCard();

    expect(screen.getByText('Fastest')).toBeInTheDocument();
    // The marks are decoration; the words are what a screen reader gets.
    expect(screen.getByText('relative cost 1 of 5')).toBeInTheDocument();
    expect(screen.getByText(/no analysis is cached/)).toBeInTheDocument();
    expect(screen.getByText(`Retires after ${formatDateOnly('2026-10-15')}`)).toBeInTheDocument();
  });

  it('says the list was checked with Anthropic, or why it is the built-in one', async () => {
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    const first = await renderCard();
    expect(screen.getByText('Checked with Anthropic just now')).toBeInTheDocument();
    first.unmount();

    vi.mocked(settingsApi.getModelOptions).mockResolvedValue({
      ...LIST, live: false, checked_at: null, live_error: 'No Claude API key configured',
      models: LIST.models.map(m => ({ ...m, available: null })),
    });
    await renderCard();
    expect(screen.getByText('Built-in list — No Claude API key configured')).toBeInTheDocument();
  });

  it('asks the server to check with Anthropic again on Refresh', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    vi.mocked(settingsApi.getModelOptions)
      .mockResolvedValueOnce({ ...LIST, live: false, checked_at: null, live_error: 'Anthropic API timed out' })
      .mockResolvedValue(LIST);
    await renderCard();
    expect(screen.getByText('Built-in list — Anthropic API timed out')).toBeInTheDocument();
    // The card's own fetch reads the server's cached list — no arguments, so
    // not TanStack's query context either.
    expect(vi.mocked(settingsApi.getModelOptions).mock.calls).toEqual([[]]);

    await user.click(screen.getByRole('button', { name: 'Refresh model list' }));

    // The forced path, not a plain refetch of the server's cached answer.
    expect(settingsApi.getModelOptions).toHaveBeenLastCalledWith(true);
    expect(await screen.findByText('Checked with Anthropic just now')).toBeInTheDocument();
  });
});

describe('ClaudeModelCard — when the saved model is on its way out', () => {
  it('says a retired model will fail, and switches in one tap', async () => {
    const user = userEvent.setup();
    let server = saved('claude-opus-4-1');
    vi.mocked(settingsApi.getModel).mockImplementation(async () => server);
    vi.mocked(settingsApi.setModel).mockImplementation(async id => (server = saved(id)));

    await renderCard();
    expect(screen.getByText(
      'Anthropic has retired Claude Opus 4.1 — analyses with it will fail.',
    )).toBeInTheDocument();
    // Never moved for the owner: the card says so and waits.
    expect(settingsApi.setModel).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Switch to Claude Opus 5.5' }));

    // Through the same save as a pick — optimistic, then checked with Claude.
    expect(settingsApi.setModel).toHaveBeenCalledWith('claude-opus-5-5');
    expect(await screen.findByText(/Reachable\./)).toBeInTheDocument();
    expect(screen.queryByText(/has retired Claude/)).not.toBeInTheDocument();
    expect((screen.getByLabelText('Model') as HTMLSelectElement).value).toBe('claude-opus-5-5');
  });

  it('rolls a one-tap switch back when the save fails, notice and all', async () => {
    // The switch is a pick like any other: it moves at once, and a refused
    // save puts back what the server still has — including the warning.
    const user = userEvent.setup();
    let reject!: (e: Error) => void;
    vi.mocked(settingsApi.getModel).mockResolvedValue(saved('claude-opus-4-1'));
    vi.mocked(settingsApi.setModel).mockReturnValue(
      new Promise<ModelStatus>((_resolve, fail) => { reject = fail; }),
    );

    const { select } = await renderCard();
    await user.click(screen.getByRole('button', { name: 'Switch to Claude Opus 5.5' }));

    expect(select.value).toBe('claude-opus-5-5');
    expect(screen.getByText('claude-opus-5-5', { selector: 'code' })).toBeInTheDocument();
    expect(screen.queryByText(/has retired Claude/)).not.toBeInTheDocument();

    // The refetch is held: only the rollback can put it back.
    let refetched!: (s: ModelStatus) => void;
    vi.mocked(settingsApi.getModel).mockReturnValue(new Promise<ModelStatus>(r => { refetched = r; }));
    reject(new Error('Model id not allowed'));

    await waitFor(() => expect(select.value).toBe('claude-opus-4-1'));
    expect(screen.getByText(/has retired Claude Opus 4\.1/)).toBeInTheDocument();
    refetched(saved('claude-opus-4-1'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Model id not allowed');
    expect(settingsApi.testApiKey).not.toHaveBeenCalled();
  });

  it('flags a retired model from the built-in list alone, naming no key', async () => {
    // No key, so nothing is "available" either way — but this build already
    // knows the model is gone, and saying nothing would wait for a failure.
    // Nor may it speak of "this key": there is none.
    vi.mocked(settingsApi.getModel).mockResolvedValue(saved('claude-opus-4-1'));
    vi.mocked(settingsApi.getModelOptions).mockResolvedValue({
      ...LIST, live: false, checked_at: null, live_error: 'No Claude API key configured',
      models: LIST.models.map(m => ({ ...m, available: null })),
    });
    await renderCard();

    const notice = screen.getByText(/has retired Claude Opus 4\.1/);
    expect(notice).not.toHaveTextContent(/key/);
    expect(screen.getByRole('button', { name: 'Switch to Claude Opus 5.5' })).toBeInTheDocument();
  });

  it('flags a current model this key cannot reach, and offers the default instead', async () => {
    // Not retired — listed for other keys, just not this one, and perhaps
    // never: so not "no longer". There is no successor to name, so the way
    // out is the default.
    vi.mocked(settingsApi.getModel).mockResolvedValue(saved('claude-fable-5-1'));
    vi.mocked(settingsApi.getModelOptions).mockResolvedValue({
      ...LIST,
      models: LIST.models.map(m => (m.id === 'claude-fable-5-1' ? { ...m, available: false } : m)),
    });
    await renderCard();

    expect(screen.getByText(
      'Anthropic doesn’t offer Claude Fable 5.1 to this key — analyses will fail.',
    )).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Switch to Claude Sonnet 5.5' })).toBeInTheDocument();
  });

  it('names the current version of a superseded model, and switches in one tap', async () => {
    const user = userEvent.setup();
    let server = saved('claude-opus-5');
    vi.mocked(settingsApi.getModel).mockImplementation(async () => server);
    vi.mocked(settingsApi.setModel).mockImplementation(async id => (server = saved(id)));

    await renderCard();
    expect(screen.getByText('Claude Opus 5.5 is the current version of this model.')).toBeInTheDocument();
    // Superseded still works — this is news, not a failure.
    expect(screen.queryByText(/analyses will fail/)).not.toBeInTheDocument();
    expect(settingsApi.setModel).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Switch to Claude Opus 5.5' }));

    expect(settingsApi.setModel).toHaveBeenCalledWith('claude-opus-5-5');
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    expect(screen.queryByText(/is the current version/)).not.toBeInTheDocument();
  });

  it('offers no move to a successor this key cannot use', async () => {
    vi.mocked(settingsApi.getModel).mockResolvedValue(saved('claude-opus-5'));
    vi.mocked(settingsApi.getModelOptions).mockResolvedValue({
      ...LIST,
      models: LIST.models.map(m => (m.id === 'claude-opus-5-5' ? { ...m, available: false } : m)),
    });
    await renderCard();

    expect(screen.queryByText(/is the current version/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Switch to/ })).not.toBeInTheDocument();
  });

  it('says nothing about a current model that is available', async () => {
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    await renderCard();
    expect(screen.queryByRole('button', { name: /^Switch to/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/has retired Claude|doesn.t offer Claude|is the current version/)).not.toBeInTheDocument();
  });
});

describe('ClaudeModelCard — without its list', () => {
  it('keeps working on the saved id when the list cannot load, and says so', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValue(saved('claude-opus-5-5'));
    vi.mocked(settingsApi.getModelOptions).mockRejectedValue(new Error('Not Found'));
    vi.mocked(settingsApi.setModel).mockResolvedValue(saved('claude-sonnet-5-5'));

    renderWithProviders(<ClaudeModelCard />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/The model list couldn.t load — Not Found/);
    // No picker with nothing in it — the id box, holding what is saved.
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    const field = screen.getByLabelText('Custom model ID');
    expect(field).toHaveValue('claude-opus-5-5');
    expect(field).not.toHaveFocus();

    await user.clear(field);
    await user.type(field, 'claude-sonnet-5-5{Enter}');
    expect(settingsApi.setModel).toHaveBeenCalledWith('claude-sonnet-5-5');
  });

  it('tries the list again on request', async () => {
    const user = userEvent.setup();
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    vi.mocked(settingsApi.getModelOptions)
      .mockRejectedValueOnce(new Error('Bad Gateway'))
      .mockResolvedValue(LIST);

    renderWithProviders(<ClaudeModelCard />);
    await user.click(await screen.findByRole('button', { name: 'Try again' }));

    const select = await screen.findByLabelText('Model') as HTMLSelectElement;
    expect(select.value).toBe('claude-sonnet-5-5');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('stays in the failed layout while it tries again', async () => {
    // A refetch of a query with no data is "pending" again in TanStack. The
    // card read that as a first load: the button just pressed and the id box
    // that still saves both vanished under a skeleton, and focus fell to the
    // page — "Trying…" was never on screen at all.
    const user = userEvent.setup();
    let land!: (list: ModelOptions) => void;
    vi.mocked(settingsApi.getModel).mockResolvedValue(saved('claude-opus-5-5'));
    vi.mocked(settingsApi.getModelOptions)
      .mockRejectedValueOnce(new Error('Bad Gateway'))
      .mockReturnValueOnce(new Promise<ModelOptions>(r => { land = r; }));

    renderWithProviders(<ClaudeModelCard />);
    await user.click(await screen.findByRole('button', { name: 'Try again' }));

    expect(await screen.findByRole('button', { name: 'Trying…' })).toBeDisabled();
    expect(screen.getByLabelText('Custom model ID')).toHaveValue('claude-opus-5-5');
    expect(screen.queryByText('Loading the model list…')).not.toBeInTheDocument();

    land(LIST);
    expect((await screen.findByLabelText('Model') as HTMLSelectElement).value).toBe('claude-opus-5-5');
  });
});

describe('ClaudeModelCard — while its list loads', () => {
  it('shows the saved model at once; only the picker waits for the list', async () => {
    // A cold server cache makes the list a live call to Anthropic, up to its
    // timeout. The card used to be whole the moment the model loaded, and
    // what it knows without the list — the model in use, Reset — still is.
    let land!: (list: ModelOptions) => void;
    vi.mocked(settingsApi.getModel).mockResolvedValue(OPUS);
    vi.mocked(settingsApi.getModelOptions).mockReturnValue(
      new Promise<ModelOptions>(r => { land = r; }),
    );

    renderWithProviders(<ClaudeModelCard />);

    expect(await screen.findByText('claude-opus-5-5', { selector: 'code' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reset to default' })).toBeInTheDocument();
    expect(screen.getByText('Loading the model list…')).toBeInTheDocument();
    // Not the saved id dropped into the custom box as if it were unknown.
    expect(screen.queryByLabelText('Custom model ID')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Model')).not.toBeInTheDocument();

    land(LIST);
    expect((await screen.findByLabelText('Model') as HTMLSelectElement).value).toBe('claude-opus-5-5');
    expect(screen.queryByText('Loading the model list…')).not.toBeInTheDocument();
  });
});

describe('ClaudeModelCard — help', () => {
  it('does not sell Haiku on speed — it measured no faster than the default here', async () => {
    vi.mocked(settingsApi.getModel).mockResolvedValue(SONNET);
    await renderCard();
    const help = screen.getByText(/^Change it for/);
    expect(help).not.toHaveTextContent(/Haiku/);
    expect(help).not.toHaveTextContent(/speed \(/);
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
    await waitFor(() => expect(select.value).toBe('claude-sonnet-5-5'));
  });
});
