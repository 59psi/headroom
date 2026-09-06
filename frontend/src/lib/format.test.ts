import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatBytes, timeAgo } from './format';

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

  it('never goes negative for a timestamp slightly in the future (clock skew)', () => {
    expect(timeAgo('2026-09-05T12:00:30Z')).toBe('just now');
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
