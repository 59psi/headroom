/**
 * Read every stylesheet under src/ into rules, for the style census tests
 * (`classes.test.ts`, `tokens.test.ts`, `touchTargets.test.ts`).
 *
 * Not imported by the app. A small parser rather than a dependency: the
 * sheets are hand-written, one level of `@media` deep at most, and what the
 * tests need is each rule's selectors, the at-rule context it sits in, and
 * its declarations — enough to ask "is this class used", "is this selector
 * defined twice", "does this control get 44px on a touchscreen".
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

export const SRC = resolve(__dirname, '..');

export interface CssRule {
  /** Path relative to src/. */
  file: string;
  line: number;
  /** The enclosing at-rules, e.g. `@media (pointer: coarse)`, joined; '' at top level. */
  context: string;
  /** The selector list, split at top-level commas (`:where(a, b)` stays whole). */
  selectors: string[];
  /** property → value, last one wins. */
  decls: Record<string, string>;
}

/** Every file under `dir` whose name passes `keep`, at any depth. */
export function walk(dir: string, keep: (name: string) => boolean, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, keep, out);
    else if (keep(name)) out.push(full);
  }
  return out;
}

export function stylesheets(): string[] {
  return walk(SRC, n => n.endsWith('.css'));
}

/** Split at commas that are not inside parentheses. */
export function splitSelectors(list: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = '';
  for (const ch of list) {
    if (ch === '(') depth++;
    if (ch === ')') depth--;
    if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

export function parseRules(file: string): CssRule[] {
  const rel = file.slice(SRC.length + 1);
  // Comments blanked to spaces (newlines kept) so offsets and lines survive.
  const css = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' '));
  const rules: CssRule[] = [];
  const stack: { head: string; line: number; body: string }[] = [];
  let buf = '';
  let line = 1;
  let bufLine = 1;
  for (const ch of css) {
    if (ch === '\n') line++;
    if (ch === '{') {
      stack.push({ head: buf.trim().replace(/\s+/g, ' '), line: bufLine, body: '' });
      buf = '';
      continue;
    }
    if (ch === '}') {
      const top = stack.pop();
      if (top) {
        top.body += buf;
        const isAt = top.head.startsWith('@');
        const isKeyframe = stack.some(s => s.head.startsWith('@keyframes'));
        if (!isAt && !isKeyframe) {
          const decls: Record<string, string> = {};
          for (const d of top.body.split(';')) {
            const m = d.match(/^\s*([-a-z]+)\s*:\s*([\s\S]+?)\s*$/);
            if (m) decls[m[1]] = m[2].replace(/\s+/g, ' ');
          }
          rules.push({
            file: rel,
            line: top.line,
            context: stack.filter(s => s.head.startsWith('@')).map(s => s.head).join(' && '),
            selectors: splitSelectors(top.head),
            decls,
          });
        }
      }
      buf = '';
      continue;
    }
    if (ch === ';' && stack.length) {
      stack[stack.length - 1].body += `${buf};`;
      buf = '';
      continue;
    }
    if (!buf.trim()) bufLine = line;
    buf += ch;
  }
  return rules;
}

export function allRules(): CssRule[] {
  return stylesheets().flatMap(parseRules);
}

/** The class names a selector names (`.a:hover > .b` → a, b). */
export function classesIn(selector: string): string[] {
  return [...selector.matchAll(/\.(-?[_a-zA-Z][_a-zA-Z0-9-]*)/g)].map(m => m[1]);
}
