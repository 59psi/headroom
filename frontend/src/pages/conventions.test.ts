/**
 * The one-definition helpers, held to by the code that used to restate them.
 *
 * Each of these was centralized once and then quietly re-inlined somewhere:
 * `/uploads/` assembled by hand beside `lib/photo.uploadUrl` (four pages and a
 * settings card), a query key typed as a string array beside `lib/queryKeys`
 * (where a typo is not an error but a second, never-invalidated cache entry —
 * four settings cards still did it after the pages had moved), and an enum
 * shown with its underscores swapped for spaces ("a game") beside the
 * server's labels. A source scan, like `test/accessibleNames.test.ts`: the
 * property is static, and a render per file would not see a code path that is
 * not taken.
 *
 * Pages, components and `lib/` alike — the rule is the app's, not a page's —
 * with the one file that DEFINES each helper left out of its own rule.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(__dirname, '..');
const SCANNED = ['pages', 'components', 'lib'];

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap(name => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return walk(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

/** Every scanned file's source with its comments blanked, so prose naming a
 *  pattern (as the "why" comments here often do) is not read as code. */
function sources(): Array<{ file: string; code: string }> {
  return SCANNED.flatMap(d => walk(join(SRC, d))).map(path => {
    const text = readFileSync(path, 'utf8');
    const code = text
      .replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' '))
      .replace(/(^|[^:])\/\/[^\n]*/g, (m, pre) => pre + ' '.repeat(m.length - pre.length));
    return { file: relative(SRC, path), code };
  });
}

function offenders(pattern: RegExp, definedIn?: string): string[] {
  const out: string[] = [];
  for (const { file, code } of sources()) {
    if (file === definedIn) continue;
    code.split('\n').forEach((line, i) => {
      if (pattern.test(line)) out.push(`${file}:${i + 1}: ${line.trim()}`);
    });
  }
  return out;
}

describe('the app uses its shared helpers', () => {
  it('scans the files it names', () => {
    // A path typo here would make every rule below pass vacuously.
    const files = sources().map(s => s.file);
    for (const dir of SCANNED) expect(files.some(f => f.startsWith(`${dir}/`))).toBe(true);
  });

  it('builds no /uploads/ URL by hand (lib/photo)', () => {
    expect(offenders(/\/uploads\//, 'lib/photo.ts')).toEqual([]);
  });

  it('types no query key as a literal array (lib/queryKeys)', () => {
    expect(offenders(/queryKey:\s*\[/)).toEqual([]);
  });

  it('makes no enum readable by swapping its underscores for spaces (useHatLabels)', () => {
    expect(offenders(/replace\(\/_\/g,\s*(['"`]) \1\)/)).toEqual([]);
  });
});
