import { describe, it, expect } from 'vitest';
import {
  matchesHatFilters, collectGeneralColors, EMPTY_HAT_FILTERS, NO_CONSTRUCTION,
  type FilterableHat, type HatFilterState,
} from './HatFilters';

function hat(over: Partial<FilterableHat> = {}): FilterableHat {
  return {
    style: 'a_game',
    size: 'classic',
    condition: 'new',
    is_beanie: false,
    construction: null,
    colors: [{ color_name: 'ocean', general_color: 'blue', hex_value: '#0af', dominance_rank: 1 }],
    ...over,
  };
}

function filters(over: Partial<HatFilterState> = {}): HatFilterState {
  return { ...EMPTY_HAT_FILTERS, ...over };
}

describe('matchesHatFilters', () => {
  it('matches everything when no filter is set', () => {
    expect(matchesHatFilters(hat(), filters())).toBe(true);
  });

  it.each([
    ['style', { style: 'odysea' }, { style: 'a_game' }],
    ['size', { size: 'small' }, { size: 'classic' }],
    ['condition', { condition: 'worn' }, { condition: 'new' }],
  ] as const)('rejects on a %s mismatch and accepts on a match', (_label, filterOn, hatHas) => {
    expect(matchesHatFilters(hat(hatHas), filters(filterOn))).toBe(false);
    expect(matchesHatFilters(hat(filterOn), filters(filterOn))).toBe(true);
  });

  it('treats type as a beanie/regular split, not a style match', () => {
    expect(matchesHatFilters(hat({ is_beanie: true }), filters({ type: 'beanie' }))).toBe(true);
    expect(matchesHatFilters(hat({ is_beanie: false }), filters({ type: 'beanie' }))).toBe(false);
    expect(matchesHatFilters(hat({ is_beanie: false }), filters({ type: 'regular' }))).toBe(true);
    expect(matchesHatFilters(hat({ is_beanie: true }), filters({ type: 'regular' }))).toBe(false);
  });

  it('matches a color when ANY swatch has it, not just the dominant one', () => {
    const twoTone = hat({
      colors: [
        { color_name: 'ocean', general_color: 'blue', hex_value: '#0af', dominance_rank: 1 },
        { color_name: 'bone', general_color: 'white', hex_value: '#fff', dominance_rank: 2 },
      ],
    });
    expect(matchesHatFilters(twoTone, filters({ color: 'white' }))).toBe(true);
    expect(matchesHatFilters(twoTone, filters({ color: 'green' }))).toBe(false);
  });

  it('ignores `room` — each page applies it differently, so it must not filter here', () => {
    // The Hats page matches room_id client-side; Search sends the room to the
    // API. If this predicate ever started applying `room`, Search would filter
    // an already-filtered list against a field it does not carry.
    expect(matchesHatFilters(hat(), filters({ room: '7' }))).toBe(true);
  });

  it('ANDs the predicates together', () => {
    const f = filters({ style: 'a_game', size: 'classic', color: 'blue' });
    expect(matchesHatFilters(hat(), f)).toBe(true);
    expect(matchesHatFilters(hat({ size: 'small' }), f)).toBe(false);
  });
});

describe('construction filter', () => {
  it('matches the hat with that construction', () => {
    const f = filters({ construction: 'HYDRO' });
    expect(matchesHatFilters(hat({ construction: 'HYDRO' }), f)).toBe(true);
    expect(matchesHatFilters(hat({ construction: 'Thermal' }), f)).toBe(false);
  });

  it('does NOT let HYDRO match HYDROLite', () => {
    // The whole reason this is equality and not a substring test. HYDRO and
    // HYDROLite are different products at different prices ($79 vs $99), and
    // "hydro" is a literal substring of "hydrolite" — a contains() check would
    // silently fold the two together in every filtered view.
    expect(
      matchesHatFilters(hat({ construction: 'HYDROLite' }), filters({ construction: 'HYDRO' })),
    ).toBe(false);
    expect(
      matchesHatFilters(hat({ construction: 'HYDRO' }), filters({ construction: 'HYDROLite' })),
    ).toBe(false);
  });

  it('ignores casing, for rows written before values were canonicalized', () => {
    expect(
      matchesHatFilters(hat({ construction: 'hydro' }), filters({ construction: 'HYDRO' })),
    ).toBe(true);
  });

  it('finds hats with no construction recorded', () => {
    const f = filters({ construction: NO_CONSTRUCTION });
    expect(matchesHatFilters(hat({ construction: null }), f)).toBe(true);
    expect(matchesHatFilters(hat({ construction: '   ' }), f)).toBe(true);
    expect(matchesHatFilters(hat({ construction: 'HYDRO' }), f)).toBe(false);
  });

  it('excludes unrecorded hats from a specific-construction filter', () => {
    expect(
      matchesHatFilters(hat({ construction: null }), filters({ construction: 'HYDRO' })),
    ).toBe(false);
  });

  it('is inert when unset', () => {
    expect(matchesHatFilters(hat({ construction: null }), filters())).toBe(true);
    expect(matchesHatFilters(hat({ construction: 'Thermal' }), filters())).toBe(true);
  });

  it('ANDs with the other filters', () => {
    const f = filters({ construction: 'HYDRO', size: 'classic' });
    expect(matchesHatFilters(hat({ construction: 'HYDRO' }), f)).toBe(true);
    expect(matchesHatFilters(hat({ construction: 'HYDRO', size: 'small' }), f)).toBe(false);
  });
});

describe('collectGeneralColors', () => {
  it('returns distinct values, sorted', () => {
    const hats = [
      hat({ colors: [{ color_name: 'a', general_color: 'red', hex_value: '#f00', dominance_rank: 1 }] }),
      hat({ colors: [{ color_name: 'b', general_color: 'blue', hex_value: '#00f', dominance_rank: 1 }] }),
      hat({ colors: [{ color_name: 'c', general_color: 'red', hex_value: '#e00', dominance_rank: 1 }] }),
    ];
    expect(collectGeneralColors(hats)).toEqual(['blue', 'red']);
  });

  it('skips blank general_color rather than offering an empty option', () => {
    const hats = [hat({
      colors: [
        { color_name: 'x', general_color: '', hex_value: '#000', dominance_rank: 1 },
        { color_name: 'y', general_color: 'black', hex_value: '#111', dominance_rank: 2 },
      ],
    })];
    expect(collectGeneralColors(hats)).toEqual(['black']);
  });

  it('handles undefined (query still loading)', () => {
    expect(collectGeneralColors(undefined)).toEqual([]);
  });
});
