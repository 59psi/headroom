/**
 * The heavy, occasional pages stay out of the main bundle.
 *
 * `App` loads Settings, Stats, Valuation, bulk import and the duplicate report
 * with `React.lazy`, so a phone's first paint does not wait on two dozen
 * settings cards and the chart code. One static `import` of any of them —
 * from `App` or from any module the main chunk pulls in — quietly folds it
 * back into the main chunk, and nothing else would notice: the app works the
 * same, only slower to start. A source scan, because the property is the
 * bundle's shape, which no render can see.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = resolve(__dirname, '..');
const LAZY_PAGES = ['SettingsPage', 'StatsPage', 'ValuationPage', 'BulkImportPage', 'DuplicatesPage'];

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap(name => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return walk(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe('pages loaded on demand', () => {
  it('are lazy in the route table', () => {
    const app = readFileSync(join(SRC, 'App.tsx'), 'utf8');
    for (const page of LAZY_PAGES) {
      expect(app).toMatch(new RegExp(`const ${page} = lazy\\(\\(\\) => import\\('\\./pages/${page}'\\)`));
    }
  });

  it('are imported statically by nothing', () => {
    const offenders: string[] = [];
    for (const path of walk(SRC)) {
      const code = readFileSync(path, 'utf8');
      for (const page of LAZY_PAGES) {
        // `from '…/Page'` is a static import; `import('…/Page')` is the lazy one.
        if (new RegExp(`from '[./]*(?:pages/)?${page}'`).test(code)) {
          offenders.push(`${relative(SRC, path)} imports ${page}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
