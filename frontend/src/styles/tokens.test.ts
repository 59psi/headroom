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

  it('every token defined is used', () => {
    // The other direction. tokens.css carried seventeen tokens nothing read —
    // a whole "aliases for legacy bootstrap overrides" block among them —
    // beside colors that had no token at all. An unused token is a second
    // name for a color, waiting to be picked instead of the live one.
    const all = walk(SRC).map(f => readFileSync(f, 'utf8')).join('\n');
    const defined = new Set<string>();
    for (const file of walk(SRC).filter(f => f.endsWith('.css'))) {
      for (const m of readFileSync(file, 'utf8').matchAll(/^\s*(--[a-z0-9-]+)\s*:/gm)) defined.add(m[1]);
    }
    const unused = [...defined].filter(t => !all.includes(`var(${t})`) && !all.includes(`var(${t},`));
    expect(unused, `tokens defined but never used:\n  ${unused.join('\n  ')}`).toEqual([]);
  });

  it('no stylesheet restates a palette color a token names', () => {
    // `rgb(var(--neon-pink-rgb) / 0.35)`, never `rgba(255, 46, 182, 0.35)`;
    // `var(--tint-green)`, never `#8dff7a`. The palette was typed out ~250
    // times across the sheets, so changing a neon meant finding every copy.
    const tokensCss = readFileSync(join(SRC, 'styles', 'tokens.css'), 'utf8');
    const channels = new Map<string, string>();
    for (const m of tokensCss.matchAll(/^\s*(--[a-z-]+-rgb):\s*(\d+) (\d+) (\d+);/gm)) {
      channels.set(`${m[2]},${m[3]},${m[4]}`, m[1]);
    }
    const hexes = new Map<string, string>();
    for (const m of tokensCss.matchAll(/^\s*(--[a-z0-9-]+):\s*(#[0-9a-f]{6});/gm)) hexes.set(m[2], m[1]);

    // main.tsx paints a bare diagnostic when the bundle itself fails to run,
    // before React — the one place that must not assume a stylesheet loaded.
    const standalone = new Set(['main.tsx']);
    const restated: string[] = [];
    for (const file of walk(SRC).filter(f => /\.(css|tsx)$/.test(f))) {
      if (standalone.has(file.slice(SRC.length + 1))) continue;
      const text = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
      const rel = file.slice(SRC.length + 1);
      for (const m of text.matchAll(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/g)) {
        const token = channels.get(`${m[1]},${m[2]},${m[3]}`);
        if (token) restated.push(`${m[0]}… is ${token} (${rel})`);
      }
      if (rel === 'styles/tokens.css') continue;
      for (const m of text.matchAll(/(?<![%\w-])(#[0-9a-fA-F]{6})\b/g)) {
        const token = hexes.get(m[1].toLowerCase());
        if (token) restated.push(`${m[1]} is ${token} (${rel})`);
      }
    }
    expect(restated, `palette colors written out instead of their token:\n  ${restated.join('\n  ')}`).toEqual([]);
  });
});
