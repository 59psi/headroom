/**
 * On a touchscreen every control is a 44px target — the house rule for tap
 * targets, which this census enforces — and the house pattern is a
 * `@media (pointer: coarse)` override on anything drawn smaller for a mouse.
 *
 * jsdom has no layout, so this reads the stylesheets instead — same shape as
 * the class and token census beside it. Two checks:
 *
 * 1. A control whose stylesheet DECLARES a height under 44px must have a
 *    coarse-pointer rule restoring 44px. The "How this works" fold was set to
 *    32px on every Settings card with no override, and the crop slider too.
 * 2. Controls that are small because of their CONTENT (a link in a line of
 *    small print) declare no height to catch, so the ones a device audit
 *    measured under 44px are listed, and each must keep its override.
 */
import { describe, expect, it } from 'vitest';
import { allRules, type CssRule } from './stylesheetCensus';

const COARSE = /\(pointer:\s*coarse\)/;
/** Contexts that never apply to a fingertip. */
const MOUSE_ONLY = /\(pointer:\s*fine\)|\(hover:\s*hover\)|\(min-width:\s*992px\)/;

/** Measured under 44px on a 390×844 touch device, content-sized. */
const AUDITED = [
  '.hr-panel-help > summary',
  '.hr-barlist-row-link',
  '.hr-footer a',
  '.hr-upkeep-event-summary a',
  '.hr-range',
  '.hr-crumb-link',
  // The analysis banners' "Settings" link (53×17) and the case header's room
  // link (88×17): single words in a sentence, each given an invisible 44px
  // hit area rather than a taller line.
  '.hr-alert-link',
  '.hr-case-room-link',
];

/** Drawn small on purpose, each with the reason a finger still gets 44px. */
const EXEMPT: Record<string, string> = {
  '.hr-cp-any-color input[type="color"]':
    'wrapped in its <label class="hr-cp-any-color">, 44px tall, which is what a tap lands on',
};

function px(value: string | undefined): number | null {
  const m = value?.match(/^(\d+(?:\.\d+)?)px$/);
  return m ? Number(m[1]) : null;
}

/** Is the last compound of `selector` something a finger presses? */
function isControl(selector: string): boolean {
  const last = selector.split(/\s*[>+~ ]\s*/).pop() ?? '';
  if (/::?(before|after)/.test(last)) return false;
  return /^(summary|button|a|select|input)\b/.test(last)
    || /\.(btn|hr-range|form-select|form-control)\b/.test(last)
    || /-(link|btn)\b/.test(last);
}

/** A coarse-pointer rule giving `selector` (or its ::after hit area) 44px. */
function hasCoarseOverride(rules: CssRule[], selector: string): boolean {
  return rules.some(r => COARSE.test(r.context) && r.selectors.some(s =>
    (s === selector || s === `${selector}::after` || s === `${selector}::before`)
    && [r.decls['min-height'], r.decls.height].some(v => (px(v) ?? 0) >= 44)));
}

describe('touch targets', () => {
  const rules = allRules();

  it('gives every control drawn under 44px a coarse-pointer override', () => {
    const short: string[] = [];
    for (const r of rules) {
      if (COARSE.test(r.context) || MOUSE_ONLY.test(r.context)) continue;
      const h = Math.max(px(r.decls['min-height']) ?? 0, px(r.decls.height) ?? 0);
      if (!h || h >= 44) continue;
      for (const sel of r.selectors) {
        if (sel in EXEMPT) continue;
        if (isControl(sel) && !hasCoarseOverride(rules, sel)) short.push(`${sel} (${h}px, ${r.file}:${r.line})`);
      }
    }
    expect(short, `controls under 44px with no (pointer: coarse) override:\n  ${short.join('\n  ')}`).toEqual([]);
  });

  it.each(AUDITED)('keeps the 44px coarse-pointer override on %s', selector => {
    expect(hasCoarseOverride(rules, selector)).toBe(true);
  });
});
