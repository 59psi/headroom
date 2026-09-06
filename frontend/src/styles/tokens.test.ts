/**
 * Every `var(--token)` the app uses is DEFINED somewhere in `src/styles`.
 *
 * An undefined custom property is not an error anywhere: the declaration is
 * simply dropped (or the fallback used), so `var(--hr-pink)` rendered in the
 * inherited color and `var(--surface-raised)` in whatever the fallback said,
 * while `tokens.css` went on defining `--neon-pink` and `--bg-elevated` for
 * the same jobs. Four such phantoms existed at 2.77.3, one of them in a card
 * whose whole point was to turn red.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(__dirname, '..');

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(css|tsx)$/.test(name) && !/\.test\.tsx$/.test(name)) out.push(full);
  }
  return out;
}

describe('design tokens', () => {
  it('every var(--x) in use is defined', () => {
    const defined = new Set<string>();
    const used = new Map<string, string[]>();
    for (const file of walk(SRC)) {
      const text = readFileSync(file, 'utf8');
      const rel = file.slice(SRC.length + 1);
      if (file.endsWith('.css')) {
        for (const m of text.matchAll(/^\s*(--[a-z0-9-]+)\s*:/gm)) defined.add(m[1]);
      }
      for (const m of text.matchAll(/var\((--[a-z0-9-]+)/g)) {
        used.set(m[1], [...(used.get(m[1]) ?? []), rel]);
      }
    }
    const phantoms = [...used.entries()]
      .filter(([token]) => !defined.has(token))
      .map(([token, files]) => `${token} (${[...new Set(files)].join(', ')})`);
    expect(phantoms, `tokens used but never defined:\n  ${phantoms.join('\n  ')}`).toEqual([]);
  });
});
