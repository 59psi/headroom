import { describe, expect, it } from 'vitest';
import { renderWithProviders } from '../../test/utils';
import { BarList, TimeSeries, type TimePoint } from './Charts';

describe('BarList', () => {
  it('draws an all-zero series as empty bars, not NaN widths that render nothing', () => {
    // A brand-new collection with no wears recorded: every value 0. Dividing
    // by a zero ceiling made every width NaN and the chart vanished, which
    // reads as a broken page rather than an empty one.
    const { container } = renderWithProviders(
      <BarList data={[{ label: 'A-Game', value: 0 }, { label: 'Odysea', value: 0 }]} />,
    );
    const fills = [...container.querySelectorAll<HTMLElement>('.hr-barlist-fill')];
    expect(fills).toHaveLength(2);
    for (const f of fills) expect(f.style.width).toBe('0%');
  });

  it('scales to the largest value, keeping a sliver for any non-zero bar', () => {
    const { container } = renderWithProviders(
      <BarList data={[{ label: 'a', value: 200 }, { label: 'b', value: 1 }]} />,
    );
    const [big, small] = [...container.querySelectorAll<HTMLElement>('.hr-barlist-fill')];
    expect(big.style.width).toBe('100%');
    expect(small.style.width).toBe('1.5%');
  });
});

describe('TimeSeries', () => {
  it('thins the axis labels to about six, so a long series does not collide on a phone', () => {
    const points: TimePoint[] = Array.from({ length: 30 }, (_, i) => ({
      key: `2024-${String(i).padStart(2, '0')}`, label: `M${i}`, value: i % 3,
    }));
    const { container } = renderWithProviders(<TimeSeries points={points} />);
    const labels = container.querySelectorAll('.hr-chart-axis');
    expect(labels.length).toBeGreaterThan(1);
    expect(labels.length).toBeLessThanOrEqual(6);
    // Every bucket is still drawn — a gap is information.
    expect(container.querySelectorAll('rect')).toHaveLength(30);
  });
});
