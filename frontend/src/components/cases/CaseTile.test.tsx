import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { caseFixture } from '../../test/fixtures';
import { CaseFillMeter, CaseTile, caseFillLabel, caseOccupancyLabel } from './CaseTile';

/** A 3-hat regular case holding `n`. Type-exclusive: the beanie side stays at 6 free. */
function regular(n: number, over = {}) {
  return caseFixture({
    hat_count: n, regular_count: n, beanie_count: 0,
    free_regular: Math.max(0, 3 - n), free_beanie: 6, nominal_capacity: 3, ...over,
  });
}

describe('caseFillLabel', () => {
  it('reports a full REGULAR case as full, though its unused beanie side is empty', () => {
    // The old test, `free_regular + free_beanie === 0`, could never be true
    // with regular hats in the case (free_beanie sits at 6), so the flag only
    // ever showed on beanie cases.
    expect(caseFillLabel(regular(3))).toBe('full');
  });

  it('reports a full beanie case, an overfull case, and nothing for room to spare', () => {
    expect(caseFillLabel(caseFixture({
      hat_count: 6, beanie_count: 6, regular_count: 0, free_beanie: 0, free_regular: 3,
      nominal_capacity: 6,
    }))).toBe('full');
    expect(caseFillLabel(regular(4, { overfull: true }))).toBe('overfull');
    expect(caseFillLabel(regular(2))).toBeNull();
    expect(caseFillLabel(regular(0))).toBeNull();
  });
});

describe('caseOccupancyLabel', () => {
  it('counts the one kind a case holds', () => {
    expect(caseOccupancyLabel(regular(0))).toBe('Empty');
    expect(caseOccupancyLabel(regular(1))).toBe('1 hat');
    expect(caseOccupancyLabel(regular(3))).toBe('3 hats');
    expect(caseOccupancyLabel(caseFixture({ hat_count: 4, beanie_count: 4, regular_count: 0 })))
      .toBe('4 beanies');
    expect(caseOccupancyLabel(caseFixture({ hat_count: 1, beanie_count: 1, regular_count: 0 })))
      .toBe('1 beanie');
  });
});

describe('CaseFillMeter', () => {
  it('fills in proportion, and never past the end of its track when overfull', () => {
    const { container, rerender } = renderWithProviders(<CaseFillMeter c={regular(2)} />);
    const fill = () => container.querySelector('.hr-case-meter > span') as HTMLElement;
    expect(parseFloat(fill().style.width)).toBeCloseTo(66.67, 1);
    rerender(<CaseFillMeter c={regular(4, { overfull: true })} />);
    expect(fill().style.width).toBe('100%');
  });
});

describe('CaseTile', () => {
  it('names the type in the same words as everywhere else, and an orphaned case as having no room', () => {
    renderWithProviders(
      <CaseTile c={caseFixture({ case_type: 'daily_wear', display_id: 'D-001', room_name: null })} />,
    );
    expect(screen.getByText(/Daily wear · No room/)).toBeInTheDocument();
  });
});
