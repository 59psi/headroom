import { describe, expect, it } from 'vitest';
import { renderHook } from '@testing-library/react';
import { PICKER_OPEN_CLASS, usePickerOpen } from './usePickerOpen';

describe('usePickerOpen', () => {
  it('keeps the nav hidden until the LAST open picker closes', () => {
    // Two pickers overlap when one opens as another closes; the closing one
    // must not bring the nav back over the list that just opened.
    const first = renderHook(({ open }) => usePickerOpen(open), { initialProps: { open: true } });
    const second = renderHook(({ open }) => usePickerOpen(open), { initialProps: { open: true } });
    expect(document.body).toHaveClass(PICKER_OPEN_CLASS);

    first.rerender({ open: false });
    expect(document.body).toHaveClass(PICKER_OPEN_CLASS);

    second.rerender({ open: false });
    expect(document.body).not.toHaveClass(PICKER_OPEN_CLASS);
  });
});
