/**
 * The color-search result list is ordered by the server on a score the UI
 * never shows, so without a label the ordering reads as broken: a hat whose
 * accent is EXACTLY your color displays Δ0 and still sits below a hat at Δ5.
 * These pin the words that explain it.
 */
import { describe, expect, it } from 'vitest';
import { matchedRankLabel } from './SearchPage';

describe('matchedRankLabel', () => {
  it('says nothing for a hat matched on its main color', () => {
    // The common case needs no explanation — every row carrying "primary"
    // would be noise on a list where most rows are exactly that.
    expect(matchedRankLabel(1)).toBe('');
  });

  it('distinguishes a secondary color from a deeper accent', () => {
    expect(matchedRankLabel(2)).toBe('secondary');
    expect(matchedRankLabel(3)).toBe('accent');
  });

  it('calls anything past the third color an accent too', () => {
    // Colors are capped at three by the analyzer but not by the manual
    // editor, and "quaternary" is not a word anyone wants on a search result.
    expect(matchedRankLabel(4)).toBe('accent');
    expect(matchedRankLabel(9)).toBe('accent');
  });

  it('treats a rank below 1 as the main color rather than labelling it', () => {
    // Not reachable through the API — every writer assigns ranks with
    // enumerate(..., start=1) — but a 0 here should degrade to the quiet
    // case, not print "accent" on a hat's primary color.
    expect(matchedRankLabel(0)).toBe('');
  });
});
