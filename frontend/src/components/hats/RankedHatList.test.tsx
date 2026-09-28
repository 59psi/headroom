/**
 * The leaderboard list on Stats and Valuation.
 *
 * The rank is drawn by the component (the list is `list-style: none`), so it
 * has to be in the text a screen reader gets: a marker-less list announces
 * no numbering of its own, and an aria-hidden digit left "Most valuable" as
 * ten hats in no stated order.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { hatFixture } from '../../test/fixtures';
import { RankedHatList } from './RankedHatList';

vi.mock('../../api/hats', () => ({
  getStyles: vi.fn(async () => [{ value: 'a_game', label: 'A-Game', is_beanie: false }]),
  getSizes: vi.fn(async () => []),
  getConditions: vi.fn(async () => []),
}));

const HATS = [
  hatFixture({ id: 1, display_id: 'A-001-01' }),
  hatFixture({ id: 2, display_id: 'A-001-02' }),
];

describe('RankedHatList', () => {
  it('puts each rank in its link, in an ordered list', () => {
    renderWithProviders(<RankedHatList hats={HATS} valueFor={() => '$10'} />);

    const list = screen.getByRole('list');
    expect(list.tagName).toBe('OL');
    const links = screen.getAllByRole('link');
    expect(links[0]).toHaveAccessibleName(/^1\.\s*A-001-01/);
    expect(links[1]).toHaveAccessibleName(/^2\.\s*A-001-02/);
    expect(links[1]).toHaveAttribute('href', '/hats/2');
  });

  it('drops the rank for a list that is ordered but not a leaderboard', () => {
    renderWithProviders(
      <RankedHatList hats={HATS} valueFor={() => 'never worn'} numbered={false} valueTone="muted" />,
    );

    expect(screen.getByRole('list').tagName).toBe('UL');
    expect(screen.getAllByRole('link')[0]).toHaveAccessibleName(/^A-001-01/);
  });

  it("names a brandless hat by its style's label, and a caseless one the shared way", async () => {
    renderWithProviders(
      <RankedHatList
        hats={[hatFixture({ id: 9, display_id: null, brand: null, style: 'a_game', model_name: null })]}
        valueFor={() => '$10'}
      />,
    );

    // The server's label, not the stored value.
    expect(await screen.findByText('A-Game')).toBeInTheDocument();
    expect(screen.queryByText('a_game')).not.toBeInTheDocument();
    expect(screen.getByText('Hat #9')).toBeInTheDocument();
  });

  it('renders the empty state instead of an empty list', () => {
    renderWithProviders(<RankedHatList hats={[]} valueFor={() => ''} empty="Nothing ranked yet." />);

    expect(screen.getByText('Nothing ranked yet.')).toBeInTheDocument();
    expect(screen.queryByRole('list')).toBeNull();
  });
});
