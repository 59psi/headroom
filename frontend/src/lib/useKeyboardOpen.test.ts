/**
 * The keyboard is inferred from how much the visual viewport shrinks — and a
 * browser's own chrome (a URL bar collapsing) shrinks it too, by much less.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { KEYBOARD_OPEN_CLASS, useKeyboardOpen } from './useKeyboardOpen';

class FakeViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.classList.remove(KEYBOARD_OPEN_CLASS);
});

function setup() {
  const vv = new FakeViewport();
  vi.stubGlobal('visualViewport', vv);
  vi.stubGlobal('innerHeight', 800);
  renderHook(() => useKeyboardOpen());
  const resize = (height: number) => act(() => {
    vv.height = height;
    vv.dispatchEvent(new Event('resize'));
  });
  return { resize };
}

describe('useKeyboardOpen', () => {
  it('ignores a URL bar collapsing — a small shrink is not a keyboard', () => {
    const { resize } = setup();
    resize(720);
    expect(document.body).not.toHaveClass(KEYBOARD_OPEN_CLASS);
  });

  it('marks the body while a keyboard-sized shrink lasts', () => {
    const { resize } = setup();
    resize(480);
    expect(document.body).toHaveClass(KEYBOARD_OPEN_CLASS);
    resize(800);
    expect(document.body).not.toHaveClass(KEYBOARD_OPEN_CLASS);
  });
});
