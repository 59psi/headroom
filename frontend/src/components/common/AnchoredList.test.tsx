/**
 * The portalled list sits against its input by measurement, so its position
 * is only as right as the last measure — these pin when it re-measures and
 * which way it opens.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { AnchoredList } from './AnchoredList';

const anchors: HTMLElement[] = [];

function anchorAt(top: number, height = 40) {
  const el = document.createElement('input');
  document.body.appendChild(el);
  anchors.push(el);
  let rect = { top, bottom: top + height, left: 16, width: 300 };
  el.getBoundingClientRect = () => ({ ...rect, right: 316, height, x: 16, y: rect.top, toJSON() {} }) as DOMRect;
  return { el, moveTo: (t: number) => { rect = { ...rect, top: t, bottom: t + height }; } };
}

afterEach(() => {
  vi.unstubAllGlobals();
  for (const el of anchors.splice(0)) el.remove();
});

describe('AnchoredList', () => {
  it('opens downward with room below', () => {
    vi.stubGlobal('visualViewport', undefined);
    vi.stubGlobal('innerHeight', 800);
    const { el } = anchorAt(100);
    render(<AnchoredList anchor={el} open role="listbox"><li>A</li></AnchoredList>);
    expect(screen.getByRole('listbox').style.top).toBe('144px');
  });

  it('flips upward at the foot of a form, where dropping down would leave it off-screen', () => {
    vi.stubGlobal('visualViewport', undefined);
    vi.stubGlobal('innerHeight', 800);
    const { el } = anchorAt(700);
    render(<AnchoredList anchor={el} open role="listbox"><li>A</li></AnchoredList>);
    const list = screen.getByRole('listbox');
    // Above the input, not below it (740 + 4).
    expect(parseFloat(list.style.top)).toBeLessThan(700);
  });

  it('follows its input when anything scrolls', () => {
    vi.stubGlobal('visualViewport', undefined);
    vi.stubGlobal('innerHeight', 800);
    const { el, moveTo } = anchorAt(100);
    render(<AnchoredList anchor={el} open role="listbox"><li>A</li></AnchoredList>);
    moveTo(50);
    act(() => { document.dispatchEvent(new Event('scroll')); });
    expect(screen.getByRole('listbox').style.top).toBe('94px');
  });
});
