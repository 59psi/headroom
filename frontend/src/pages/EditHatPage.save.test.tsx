/**
 * What a save sends, and what it says when part of it fails.
 *
 * The form saves in up to four requests (details, placement, colors, photo).
 * These pin the ones that went wrong: a cleared date that was never sent, a
 * failure after the first write that claimed nothing was saved and refreshed
 * nothing, a palette re-sent on every save (which now marks it as the
 * owner's), and colors added by hand all stamped "primary".
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { hatFixture } from '../test/fixtures';
import { EditHatPage } from './EditHatPage';
import * as hatsApi from '../api/hats';
import { ApiError } from '../api/client';
import type { ColorTag, HatRead } from '../types';

const COLORS: ColorTag[] = [
  { color_name: 'navy', general_color: 'blue', hex_value: '#000080', dominance_rank: 1, tier: 'primary' },
  { color_name: 'hot pink', general_color: 'pink', hex_value: '#ff2eb6', dominance_rank: 2, tier: 'accent' },
];

const HAT: HatRead = hatFixture({
  id: 7, display_id: 'H-007', brand: 'melin', model_name: 'Coronado',
  date_last_worn: '2026-01-02', colors: COLORS, analysis_status: 'ok',
});

vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()) };
});
vi.mock('../api/cases', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), listCases: vi.fn(async () => []) };
});
vi.mock('../api/rooms', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return { ...stubAll(await importOriginal<object>()), getRoomOptions: vi.fn(async () => []) };
});
vi.mock('react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router')>()),
  useParams: () => ({ hatId: '7' }),
  useNavigate: () => vi.fn(),
}));

const mocked = vi.mocked(hatsApi);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.getHat.mockResolvedValue(HAT);
  mocked.updateHat.mockResolvedValue(HAT);
  mocked.updateHatColors.mockResolvedValue(HAT);
  mocked.getStyles.mockResolvedValue([{ value: 'a_game', label: 'A-Game', is_beanie: false }]);
  mocked.getSizes.mockResolvedValue([{ value: 'classic', label: 'Classic' }]);
  mocked.getConditions.mockResolvedValue([{ value: 'new', label: 'New' }]);
  mocked.getConstructions.mockResolvedValue([]);
  mocked.getCollections.mockResolvedValue([]);
  mocked.getColorwayOptions.mockResolvedValue([]);
});

async function save(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
}

describe('EditHatPage — the last-worn date', () => {
  it('sends null when the date is cleared, so the clear is saved', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    const date = await screen.findByLabelText('Date last worn');
    expect(date).toHaveValue('2026-01-02');
    await user.clear(date);
    await save(user);

    await waitFor(() => expect(mocked.updateHat).toHaveBeenCalled());
    expect(mocked.updateHat.mock.calls[0][1]).toHaveProperty('date_last_worn', null);
  });

  it('leaves an untouched date alone, so a wear logged while the form was open stands', async () => {
    // Opened with no date; a tag scan logs today's wear before the save.
    // Sending the (empty) seed would have written null over it.
    const user = userEvent.setup();
    mocked.getHat.mockResolvedValue({ ...HAT, date_last_worn: null });
    renderWithProviders(<EditHatPage />);

    await user.type(await screen.findByLabelText('Brand'), ' x');
    await save(user);

    await waitFor(() => expect(mocked.updateHat).toHaveBeenCalled());
    expect(mocked.updateHat.mock.calls[0][1]).not.toHaveProperty('date_last_worn');
  });

  it('sends a date that was changed', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    const date = await screen.findByLabelText('Date last worn');
    await user.clear(date);
    await user.type(date, '2026-02-03');
    await save(user);

    await waitFor(() => expect(mocked.updateHat).toHaveBeenCalled());
    expect(mocked.updateHat.mock.calls[0][1]).toHaveProperty('date_last_worn', '2026-02-03');
  });
});

describe('EditHatPage — a save that fails part-way', () => {
  it('names what was saved and what was not, and refreshes what did land', async () => {
    const user = userEvent.setup();
    mocked.updateHatColors.mockRejectedValue(new ApiError('database is locked', 503));
    const { client } = renderWithProviders(<EditHatPage />);
    const invalidate = vi.spyOn(client, 'invalidateQueries');

    await user.click(await screen.findByRole('button', { name: 'Remove color 2' }));
    await save(user);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Partly saved');
    expect(alert).toHaveTextContent('Details saved; colors not saved: database is locked');
    expect(alert).not.toHaveTextContent('Not saved');
    // The brand change DID land — the hat page must not keep the old row.
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['hat', 7] }));
    expect(screen.queryByText('Changes saved')).toBeNull();
  });

  it('says "Not saved" when the first write fails and nothing landed', async () => {
    const user = userEvent.setup();
    mocked.updateHat.mockRejectedValue(new ApiError('date_last_worn: cannot be in the future', 422));
    renderWithProviders(<EditHatPage />);

    await screen.findByLabelText('Date last worn');
    await save(user);

    expect(await screen.findByRole('alert')).toHaveTextContent('Not saved — date_last_worn: cannot be in the future');
  });
});

describe('EditHatPage — the palette is sent only when it changed', () => {
  it('leaves an untouched palette alone', async () => {
    // Sending it would claim the analyzer's colors as the owner's, and a
    // re-analysis would never touch them again.
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    await user.type(await screen.findByLabelText('Brand'), ' x');
    await save(user);

    await waitFor(() => expect(mocked.updateHat).toHaveBeenCalled());
    expect(await screen.findByText('Changes saved')).toBeInTheDocument();
    expect(mocked.updateHatColors).not.toHaveBeenCalled();
  });

  it('sends the palette once a color is changed', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    const name = await screen.findByLabelText('Color 1 name');
    await user.clear(name);
    await user.type(name, 'midnight');
    await save(user);

    await waitFor(() => expect(mocked.updateHatColors).toHaveBeenCalled());
    expect(mocked.updateHatColors.mock.calls[0][1][0]).toMatchObject({ color_name: 'midnight', tier: 'primary' });
  });
});

describe('EditHatPage — a color added by hand', () => {
  it('starts at the tier its place in the list implies, and the owner can change it', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    await user.click(await screen.findByRole('button', { name: '+ Add color' }));
    // Third in the list: tertiary, not "primary" for every added color.
    const tier = screen.getByLabelText('Color 3 tier');
    expect(tier).toHaveValue('tertiary');
    await user.selectOptions(tier, 'accent');
    await save(user);

    await waitFor(() => expect(mocked.updateHatColors).toHaveBeenCalled());
    const sent = mocked.updateHatColors.mock.calls[0][1];
    expect(sent).toHaveLength(3);
    // Sent blank, so the server names it after its hex's palette color.
    expect(sent[2]).toMatchObject({ color_name: '', tier: 'accent' });
  });
});

describe('EditHatPage — a hat that would not load', () => {
  it('says why and offers the way back', async () => {
    mocked.getHat.mockRejectedValue(new ApiError('database is locked', 500));
    renderWithProviders(<EditHatPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('database is locked');
    expect(screen.getByRole('link', { name: /Back to the hat/ })).toHaveAttribute('href', '/hats/7');
  });
});
