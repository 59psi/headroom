import { vi } from 'vitest';

/**
 * Every function export of `real` replaced by a `vi.fn()`; everything else
 * (constants, classes, types' runtime values) kept as it is.
 *
 * For `vi.mock` factories: `{ ...stubAll(await importOriginal()), ...overrides }`.
 *
 * A hand-listed factory — `vi.mock('../api/x', () => ({ a: vi.fn() }))` —
 * mocks the module's shape as of the day the test was written. The first
 * time the component under test imports one more export, Vitest throws
 * `No "<name>" export is defined on the mock`, in a test that never touched
 * the new thing. It happened to the Settings roster test in three
 * consecutive releases and to the Trust-this-device test the moment its card
 * started reading a URL constant from the API module. Deriving the mock from
 * the real module's keys means adding an export never breaks a test that
 * does not use it; the test still names the exports whose behavior it fixes.
 *
 * Classes are kept rather than stubbed because `instanceof` checks against
 * them (`ApiError`) must keep working through the mock.
 */
export function stubAll<T extends object>(real: T): T {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(real)) {
    const isFn = typeof value === 'function';
    const isClass = isFn && /^class\s/.test(Function.prototype.toString.call(value));
    out[key] = isFn && !isClass ? vi.fn() : value;
  }
  return out as T;
}
