/**
 * The swatch editor: removing asks first in the app's dialog (Cancel keeps
 * the swatch), and a save puts the server's answer straight into the hat's
 * cache so the palette under the modal is right the moment it closes.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useQuery } from '@tanstack/react-query';
import { renderWithProviders } from '../../test/utils';
import { hatFixture } from '../../test/fixtures';
import { ColorEditModal } from './ColorEditModal';
import * as hatsApi from '../../api/hats';
import type { ColorTag, HatRead } from '../../types';

vi.mock('../../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return { ...stubAll(await importOriginal<object>()) };
});

const mocked = vi.mocked(hatsApi);

const COLORS: ColorTag[] = [
  { color_name: 'navy', general_color: 'blue', hex_value: '#000080', dominance_rank: 1, tier: 'primary' },
  { color_name: 'hot pink', general_color: 'pink', hex_value: '#ff2eb6', dominance_rank: 2, tier: 'accent' },
  { color_name: 'bone', general_color: 'white', hex_value: '#f0ead6', dominance_rank: 3, tier: 'secondary' },
];

beforeEach(() => vi.clearAllMocks());

/**
 * Observes `['hat', 5]` the way the hat page does, so the cache entry the
 * modal writes is kept (the test client's `gcTime: 0` drops unobserved ones).
 * Its fetch never answers, so what the cache holds is only what the modal
 * put there — a refetch cannot stand in for it.
 */
function HatPageStandIn() {
  useQuery({ queryKey: ['hat', 5], queryFn: () => new Promise<HatRead>(() => {}) });
  return null;
}

describe('ColorEditModal — remove', () => {
  it('asks first, and Cancel keeps the swatch and the editor', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderWithProviders(<ColorEditModal hatId={5} colors={COLORS} editingRank={1} onClose={onClose} />);

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Remove this color?' });
    await user.click(within(confirm).getByRole('button', { name: 'Cancel' }));

    expect(mocked.updateHatColors).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('removes once confirmed, keeping the rest in order — their position is their rank', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mocked.updateHatColors.mockResolvedValue(hatFixture());
    renderWithProviders(<ColorEditModal hatId={5} colors={COLORS} editingRank={1} onClose={onClose} />);

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    const confirm = await screen.findByRole('alertdialog', { name: 'Remove this color?' });
    await user.click(within(confirm).getByRole('button', { name: 'Remove color' }));

    await waitFor(() => expect(mocked.updateHatColors).toHaveBeenCalledTimes(1));
    expect(mocked.updateHatColors.mock.calls[0][1].map(c => c.hex_value)).toEqual([
      COLORS[1].hex_value, COLORS[2].hex_value,
    ]);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(screen.getByText('Color removed')).toBeInTheDocument();
  });
});

describe('ColorEditModal — save', () => {
  it('writes the server’s answer into the hat cache and closes', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    // The server derives `general_color` from the hex when the box is blank —
    // the cache must hold ITS answer, not what the form sent.
    const saved = hatFixture({ colors: [{ ...COLORS[0], general_color: 'navy-derived' }] });
    mocked.updateHatColors.mockResolvedValue(saved);
    const { client } = renderWithProviders(
      <>
        <HatPageStandIn />
        <ColorEditModal hatId={5} colors={COLORS.slice(0, 1)} editingRank={1} onClose={onClose} />
      </>,
    );

    await user.clear(screen.getByLabelText('General color (for filters)'));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(mocked.updateHatColors.mock.calls[0][1][0]).toMatchObject({ general_color: '' });
    expect(client.getQueryData<HatRead>(['hat', 5])?.colors[0].general_color).toBe('navy-derived');
    expect(screen.getByText('Color saved')).toBeInTheDocument();
  });

  it('picks the tier with one tap', async () => {
    const user = userEvent.setup();
    mocked.updateHatColors.mockResolvedValue(hatFixture());
    renderWithProviders(<ColorEditModal hatId={5} colors={COLORS} editingRank={null} onClose={vi.fn()} />);

    const accent = screen.getByRole('button', { name: 'Accent' });
    await user.click(accent);
    expect(accent).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Primary' })).toHaveAttribute('aria-pressed', 'false');

    await user.click(screen.getByRole('button', { name: 'Add color' }));
    await waitFor(() => expect(mocked.updateHatColors).toHaveBeenCalled());
    const sent = mocked.updateHatColors.mock.calls[0][1];
    expect(sent).toHaveLength(4);
    expect(sent[3]).toMatchObject({ tier: 'accent' });
  });

  it('starts a new color at the tier its position implies, and lets the server name a blank one', async () => {
    const user = userEvent.setup();
    mocked.updateHatColors.mockResolvedValue(hatFixture());
    renderWithProviders(
      <ColorEditModal hatId={5} colors={COLORS.slice(0, 2)} editingRank={null} onClose={vi.fn()} />,
    );

    // The third color of a palette is its tertiary, not another "primary".
    expect(screen.getByRole('button', { name: 'Tertiary' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Add color' }));
    await waitFor(() => expect(mocked.updateHatColors).toHaveBeenCalled());
    // Blank is "name it from the hex" — never the literal word "unnamed".
    expect(mocked.updateHatColors.mock.calls[0][1][2]).toMatchObject({ color_name: null, tier: 'tertiary' });
  });

  it('refreshes every view that shows the palette, not only the hat and the list', async () => {
    const user = userEvent.setup();
    mocked.updateHatColors.mockResolvedValue(hatFixture());
    const { client } = renderWithProviders(
      <ColorEditModal hatId={5} colors={COLORS} editingRank={2} onClose={vi.fn()} />,
    );
    const invalidate = vi.spyOn(client, 'invalidateQueries');

    await user.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText('Color saved');

    const keys = invalidate.mock.calls.map(([f]) => JSON.stringify(f?.queryKey));
    for (const k of [['hat', 5], ['hats'], ['room'], ['case'], ['search']]) {
      expect(keys).toContain(JSON.stringify(k));
    }
  });

  it('keeps the editor open and says why when the save fails', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    mocked.updateHatColors.mockRejectedValue(new Error('invalid hex'));
    renderWithProviders(<ColorEditModal hatId={5} colors={COLORS} editingRank={2} onClose={onClose} />);

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText(/invalid hex/)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
