/**
 * Every Settings card leads with a status and folds its explanation away —
 * the shape the Settings page promises and USAGE describes.
 *
 * Three action cards (collection export, inventory report, share target)
 * shipped with no status pill, and four (account, guest view, logo, share
 * target) with their "how this works" text unfolded, while the release notes
 * said every card had both. A source census, like the stylesheet ones: the
 * property is "each card's Panel is given these props", which no single
 * render would check for the cards it does not mount.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const DIR = resolve(__dirname);

/** Cards whose Panel is another card's — they inherit its status and fold. */
const WRAPPERS: Record<string, string> = {
  'AnthropicKeyCard.tsx': 'renders KeyCard',
  'GoogleVisionKeyCard.tsx': 'renders KeyCard',
};

const cards = readdirSync(DIR).filter(n => /Card\.tsx$/.test(n) && !(n in WRAPPERS));

describe('Settings cards', () => {
  it('finds the cards', () => {
    expect(cards.length).toBeGreaterThan(20);
  });

  it.each(cards)('%s leads with a status and folds its help', name => {
    const code = readFileSync(join(DIR, name), 'utf8');
    expect(code).toMatch(/<Panel\b/);
    // The prop itself — not a `data-status=` or `helpLabel=` that merely
    // ends in the same letters.
    expect(code).toMatch(/(?<![\w-])status=\{/);
    expect(code).toMatch(/(?<![\w-])help=\{/);
  });

  it.each(Object.keys(WRAPPERS))('%s is really a KeyCard wrapper', name => {
    expect(readFileSync(join(DIR, name), 'utf8')).toMatch(/<KeyCard\b/);
  });
});
