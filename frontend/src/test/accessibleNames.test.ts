/**
 * Every form control has an accessible name.
 *
 * CLAUDE.md states the rule for query controls ("must carry `aria-label` — the
 * visible `<label>` elements have no `htmlFor`, so nothing else associates
 * them") and calls it an accessibility requirement first. The 2026-08 review
 * fixed eleven; twenty-six more were unlabeled at 2.77.3, including Login's
 * username and password, every API-key box, and the whole Edit-hat form. A
 * screen reader read each as "edit text".
 *
 * A source scan rather than a render of every form: rendering needs a mock per
 * page, and the property is static. A control passes when it carries
 * `aria-label`/`aria-labelledby`, or an `id` that some `htmlFor` in the same
 * file points at, or is `type="hidden"`/`type="submit"`/`type="file"` inside a
 * labeled wrapper (file inputs are named by their `<label>` via `htmlFor` too,
 * so they are not exempt — only hidden and submit are).
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(__dirname, '..');

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx$/.test(name) && !/\.test\.tsx$/.test(name)) out.push(full);
  }
  return out;
}

/** Each `<input …>`, `<select …>`, `<textarea …>` opening tag with its attributes. */
function controls(text: string): Array<{ tag: string; attrs: string; line: number }> {
  const out: Array<{ tag: string; attrs: string; line: number }> = [];
  // Blank out comments (block, line and JSX) so a `<select>` mentioned in prose
  // is not read as a control — same length, so line numbers stay right.
  const code = text
    .replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' '))
    .replace(/(^|[^:])\/\/[^\n]*/g, (m, pre) => pre + ' '.repeat(m.length - pre.length));
  // Walk to the tag's closing `>` by hand: an attribute like
  // `onChange={e => setX(e.target.value)}` contains `>` inside braces, and a
  // regex that stops at the first `>` truncates the attribute list — which is
  // how `aria-label` set AFTER such an attribute went unseen.
  const open = /<(input|select|textarea)\b/g;
  for (const m of code.matchAll(open)) {
    let i = m.index! + m[0].length;
    let depth = 0;
    while (i < code.length) {
      const ch = code[i];
      if (ch === '{') depth++;
      else if (ch === '}') depth--;
      else if (ch === '>' && depth === 0) break;
      i++;
    }
    const line = text.slice(0, m.index).split('\n').length;
    out.push({ tag: m[1], attrs: code.slice(m.index! + m[0].length, i), line });
  }
  return out;
}

describe('form controls', () => {
  it('each has an accessible name', () => {
    const unnamed: string[] = [];
    for (const file of walk(SRC)) {
      const text = readFileSync(file, 'utf8');
      const rel = file.slice(SRC.length + 1);
      const htmlFors = new Set([...text.matchAll(/htmlFor=\{?["'`]([^"'`}]+)["'`]?\}?/g)].map(m => m[1]));
      const templateFors = [...text.matchAll(/htmlFor=\{`([^`]+)`\}/g)].map(m => m[1].replace(/\$\{[^}]*\}/g, ''));
      // `htmlFor={provider.inputId}` — an expression, matched against the
      // control's `id={…}` by its text. A shared component (KeyCard) takes the
      // id as a prop, and the pairing is just as real as a literal one.
      const exprFors = new Set([...text.matchAll(/htmlFor=\{([A-Za-z_$][\w$.]*)\}/g)].map(m => m[1]));
      for (const c of controls(text)) {
        if (/type=["'](hidden|submit)["']/.test(c.attrs)) continue;
        // A `hidden` file input is driven by a visible, labeled button.
        if (/\bhidden\b/.test(c.attrs) && /type=["']file["']/.test(c.attrs)) continue;
        if (/aria-label(ledby)?=/.test(c.attrs)) continue;
        const id = c.attrs.match(/\bid=\{?["'`]([^"'`}]+)["'`]?\}?/) ?? c.attrs.match(/\bid=\{`([^`]+)`\}/);
        if (id) {
          const literal = id[1].replace(/\$\{[^}]*\}/g, '');
          if (htmlFors.has(id[1]) || templateFors.some(f => f && literal.startsWith(f.split('${')[0]))) continue;
        }
        const exprId = c.attrs.match(/\bid=\{([A-Za-z_$][\w$.]*)\}/);
        if (exprId && exprFors.has(exprId[1])) continue;
        unnamed.push(`${rel}:${c.line} <${c.tag}>`);
      }
    }
    expect(unnamed, `controls with no accessible name:\n  ${unnamed.join('\n  ')}`).toEqual([]);
  });
});
