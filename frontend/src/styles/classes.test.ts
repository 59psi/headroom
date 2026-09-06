/**
 * Every class the components apply has a rule somewhere.
 *
 * `app.css` replaced Bootstrap, so a Bootstrap-era class name with no rule here
 * silently does nothing — and eleven of them were in use at 2.77.3: the price /
 * date row had no 7/5 split, the frozen-price list showed bullets, the audit
 * table was a browser default, the guest switch was a plain checkbox, the
 * queue's row spinner was an empty span, and on the Duplicates page the more
 * serious `exact` badge fell through to the neutral style while `likely` got
 * yellow. A class that renders nothing looks like a design decision.
 *
 * Same shape as the backend's parity tests: read the source, compare, fail on
 * drift. Dynamic class fragments (`hr-badge-${condition}`) are checked by their
 * static prefix.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(__dirname, '..');

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(full);
  }
  return out;
}

/** Class selectors defined across every stylesheet under src/. */
function definedClasses(): Set<string> {
  const css = readdirSync(join(SRC, 'styles'))
    .filter((f: string) => f.endsWith('.css'))
    .map((f: string) => readFileSync(join(SRC, 'styles', f), 'utf8'))
    .join('\n')
    + readFileSync(join(SRC, 'components/layout/BottomNav.css'), 'utf8');
  const defined = new Set<string>();
  for (const m of css.matchAll(/\.(-?[_a-zA-Z][_a-zA-Z0-9-]*)/g)) defined.add(m[1]);
  return defined;
}

/** Class literals used in `className="..."` and template strings in the TSX. */
function usedClasses(): Map<string, string[]> {
  const used = new Map<string, string[]>();
  for (const file of walk(SRC)) {
    const text = readFileSync(file, 'utf8');
    const rel = file.slice(SRC.length + 1);
    // className="a b c"
    for (const m of text.matchAll(/className="([^"]+)"/g)) {
      for (const cls of m[1].split(/\s+/)) if (cls) (used.get(cls) ?? used.set(cls, []).get(cls)!).push(rel);
    }
    // className={`a b ${expr} c`} — keep the static tokens only
    for (const m of text.matchAll(/className=\{`([^`]+)`\}/g)) {
      const staticPart = m[1].replace(/\$\{[^}]*\}/g, ' ');
      for (const cls of staticPart.split(/\s+/)) if (cls && !cls.includes('$')) (used.get(cls) ?? used.set(cls, []).get(cls)!).push(rel);
    }
    // className={cond ? 'a b' : 'c d'} — only the literals in ternary BRANCHES
    // (after `?` or `:`), never the values being compared (`x === 'all'`).
    for (const m of text.matchAll(/className=\{([^}]*)\}/g)) {
      for (const lit of m[1].matchAll(/(?<![?])[?:]\s*'([^']+)'/g)) {
        for (const cls of lit[1].split(/\s+/)) if (cls && /^-?[_a-zA-Z][_a-zA-Z0-9-]*$/.test(cls)) (used.get(cls) ?? used.set(cls, []).get(cls)!).push(rel);
      }
    }
    // className={'a b' + expr} — the leading string literal in a concatenation
    // (CasePicker/Combobox build option classes this way; the scanner missed
    // them, so a typo'd class there was invisible).
    for (const m of text.matchAll(/className=\{\s*'([^']+)'/g)) {
      for (const cls of m[1].split(/\s+/)) if (cls) (used.get(cls) ?? used.set(cls, []).get(cls)!).push(rel);
    }
    // classList.add/toggle/remove('literal') and *_CLASS constants — the
    // keyboard/picker body classes are string constants matched only by a CSS
    // selector, so nothing checked they exist and a rename left the feature
    // silently gone. Scanned in .ts too (this walk now includes it).
    for (const m of text.matchAll(/classList\.(?:add|toggle|remove)\(\s*'([^']+)'/g)) {
      for (const cls of m[1].split(/\s+/)) if (cls) (used.get(cls) ?? used.set(cls, []).get(cls)!).push(rel);
    }
    for (const m of text.matchAll(/_CLASS\s*=\s*'([^']+)'/g)) {
      for (const cls of m[1].split(/\s+/)) if (cls) (used.get(cls) ?? used.set(cls, []).get(cls)!).push(rel);
    }
  }
  return used;
}

describe('stylesheet parity', () => {
  it('defines a rule for every class the components apply', () => {
    const defined = definedClasses();
    const missing: string[] = [];
    for (const [cls, files] of usedClasses()) {
      // `hr-badge-` / `hr-tile-`: a dynamic suffix follows; the prefix must
      // match SOME defined class or nothing it produces can be styled.
      const ok = cls.endsWith('-')
        ? [...defined].some(d => d.startsWith(cls))
        : defined.has(cls);
      if (!ok) missing.push(`${cls}  (${[...new Set(files)].slice(0, 3).join(', ')})`);
    }
    expect(missing, `classes used in TSX with no rule in any stylesheet:\n  ${missing.join('\n  ')}`).toEqual([]);
  });
});
