import { describe, expect, it } from 'vitest';
import { optionLabel } from './labels';

describe('optionLabel', () => {
  const styles = [{ value: 'a_game', label: 'A-Game' }, { value: 'odysea', label: 'Odysea' }];

  it('reads the server’s label for a stored value', () => {
    // The hat page printed `a_game` as "a game" while the filter chip for the
    // very same value said "A-Game" — two spellings of one fact on one screen.
    expect(optionLabel(styles, 'a_game')).toBe('A-Game');
  });

  it('falls back to a readable form before the options load, or for a value they lack', () => {
    expect(optionLabel(undefined, 'x_large')).toBe('X Large');
    expect(optionLabel(styles, 'the_shore')).toBe('The Shore');
  });

  it('matches numeric option values by their string form', () => {
    expect(optionLabel([{ value: 3, label: 'Office' }], '3')).toBe('Office');
  });
});
