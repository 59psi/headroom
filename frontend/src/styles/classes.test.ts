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
import { allRules, classesIn } from './stylesheetCensus';

const SRC = resolve(__dirname, '..');

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(full);
  }
  return out;
}

/** Every stylesheet under src/, at any depth. */
function stylesheets(dir: string = SRC, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) stylesheets(full, out);
    else if (name.endsWith('.css')) out.push(full);
  }
  return out;
}

/** Class selectors defined across every stylesheet under src/.
 *
 *  Walked, not listed. This read `styles/*.css` plus one named component
 *  sheet, so when the per-area sheets arrived in `styles/areas/` every class
 *  defined there — a few hundred of them — reported as missing, and a census
 *  that fails on every run is a census nobody reads. */
function definedClasses(): Set<string> {
  const css = stylesheets().map(f => readFileSync(f, 'utf8')).join('\n');
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

  it('applies every class a stylesheet defines — no rule styles nothing', () => {
    // The other direction. About 75 Bootstrap-replacement utilities and
    // several component rules (a switch, a spinner, a fill tag) sat in
    // app.css long after the last element using them was gone, and nothing
    // could say so: the census above only asks "used ⇒ defined". A rule that
    // styles nothing is not free — it is a second answer waiting for the day
    // someone applies the class, and a claim the stylesheet makes about the
    // app that is no longer true.
    //
    // "Applied" is loose on purpose: ANY identifier-shaped token in the
    // source counts, so a class built up in a helper or kept in a table
    // passes. A dynamic prefix (`hr-badge-${…}`, `'opt-' + …`) covers every
    // class that starts with it.
    const code = [...walk(SRC), resolve(SRC, '..', 'index.html')]
      .map(f => readFileSync(f, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"])\/\/.*$/gm, '$1'))
      .join('\n');
    const tokens = new Set(code.match(/[A-Za-z_][A-Za-z0-9_-]*/g));
    const prefixes = new Set<string>();
    for (const m of code.matchAll(/([A-Za-z_][A-Za-z0-9_-]*-)\$\{/g)) prefixes.add(m[1]);
    for (const m of code.matchAll(/['"`]([A-Za-z_][A-Za-z0-9_-]*-)['"`]\s*\+/g)) prefixes.add(m[1]);

    const unused = new Map<string, string>();
    for (const rule of allRules()) {
      for (const sel of rule.selectors) {
        for (const cls of classesIn(sel)) {
          if (tokens.has(cls) || [...prefixes].some(p => cls.startsWith(p))) continue;
          unused.set(cls, `${rule.file}:${rule.line}`);
        }
      }
    }
    const report = [...unused].map(([cls, at]) => `.${cls}  (${at})`);
    expect(report, `classes defined in a stylesheet that nothing applies:\n  ${report.join('\n  ')}`).toEqual([]);
  });

  it('defines each selector in ONE stylesheet', () => {
    // Twenty-eight selectors were set in two sheets with conflicting values,
    // and which one won depended only on the import order in main.tsx — so a
    // fix made in the losing sheet did nothing, and one wrong rule (the
    // footer's doubled bottom-nav padding) was "fixed" by an override in the
    // other sheet instead of being removed. One owner per selector — in any
    // at-rule context, since that bug was exactly a media-query copy fighting
    // the base rule in another sheet. Within one sheet a selector may repeat
    // (a base rule plus its media variants); across sheets it may not.
    // Selectors that name a class, i.e. a component's: a universal or bare
    // element reset (`*`, `html`) is base-layer by nature, and the reduced-
    // motion override of `*` in app.css is not a second owner of tokens.css's
    // box-sizing reset.
    const owners = new Map<string, Set<string>>();
    for (const rule of allRules()) {
      for (const sel of rule.selectors) {
        if (!classesIn(sel).length) continue;
        (owners.get(sel) ?? owners.set(sel, new Set()).get(sel)!).add(`${rule.file}:${rule.line}`);
      }
    }
    const shared = [...owners]
      .filter(([, at]) => new Set([...at].map(a => a.split(':')[0])).size > 1)
      .map(([sel, at]) => `${sel}  (${[...at].join(', ')})`);
    expect(shared, `selectors defined in more than one stylesheet:\n  ${shared.join('\n  ')}`).toEqual([]);
  });

  it('only counts stylesheets something actually imports', () => {
    // The census above treats every .css file under src/ as live. A sheet no
    // module imports never reaches the page, so its rules would satisfy the
    // census while styling nothing — the exact failure it exists to catch.
    const sources = walk(SRC).map(f => readFileSync(f, 'utf8')).join('\n');
    const orphans = stylesheets()
      .map(f => f.slice(f.lastIndexOf('/') + 1))
      .filter(name => !sources.includes(`/${name}'`) && !sources.includes(`./${name}'`));
    expect(orphans, 'stylesheets under src/ that no module imports').toEqual([]);
  });
});
