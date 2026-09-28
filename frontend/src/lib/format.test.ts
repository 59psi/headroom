import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatBytes, noun, plural, timeAgo } from './format';

describe('timeAgo', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-09-05T12:00:00Z')); });
  afterEach(() => { vi.useRealTimers(); });

  it('says never for nothing, and steps through the units', () => {
    expect(timeAgo(null)).toBe('never');
    expect(timeAgo('2026-09-05T11:59:50Z')).toBe('just now');
    expect(timeAgo('2026-09-05T11:56:00Z')).toBe('4 min ago');
    expect(timeAgo('2026-09-05T09:00:00Z')).toBe('3 h ago');
    expect(timeAgo('2026-09-03T12:00:00Z')).toBe('2 days ago');
  });

  it('keeps counting hours through the first two days — "1 days ago" for 30 hours is a rounding lie', () => {
    expect(timeAgo('2026-09-04T06:00:00Z')).toBe('30 h ago');
    expect(timeAgo('2026-09-03T13:00:00Z')).toBe('47 h ago');
  });

  it('never goes negative for a timestamp slightly in the future (clock skew)', () => {
    expect(timeAgo('2026-09-05T12:00:30Z')).toBe('just now');
  });
});

describe('plural / noun', () => {
  it('agrees with the count, including 0', () => {
    expect(plural(1, 'hat')).toBe('1 hat');
    expect(plural(0, 'hat')).toBe('0 hats');
    expect(plural(2, 'hat')).toBe('2 hats');
  });

  it('takes an irregular plural', () => {
    expect(noun(1, 'has', 'have')).toBe('has');
    expect(noun(3, 'has', 'have')).toBe('have');
    expect(plural(2, 'copy', 'copies')).toBe('2 copies');
  });
});

describe('formatBytes', () => {
  it('picks the unit', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(3.4 * 1024)).toBe('3.4 KB');
    expect(formatBytes(12 * 1024 ** 2)).toBe('12.0 MB');
    expect(formatBytes(1.25 * 1024 ** 3)).toBe('1.25 GB');
  });
});
