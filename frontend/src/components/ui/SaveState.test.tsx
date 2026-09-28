import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { SaveState, mutationSaveStatus, type SaveStatus } from './SaveState';

/**
 * The acknowledgement beside a field that saves itself. "Saved" must appear
 * after every save — including the second of two in a row — and then get out
 * of the way; a failure must stay until something replaces it.
 */
beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

function note() {
  return screen.getByRole('status');
}

describe('SaveState', () => {
  it('idle: an empty live region, already mounted for the first message', () => {
    render(<SaveState status="idle" />);
    expect(note()).toBeEmptyDOMElement();
  });

  it.each<[SaveStatus, string, string]>([
    ['saving', 'Saving…', 'is-busy'],
    ['pending', 'Unsaved changes', 'is-pending'],
    ['error', 'Not saved', 'is-error'],
    ['saved', 'Saved', 'is-ok'],
  ])('%s reads "%s"', (status, text, tone) => {
    render(<SaveState status={status} />);
    act(() => {}); // let the "saved" effect run
    expect(note()).toHaveTextContent(text);
    expect(note()).toHaveClass(tone);
  });

  it('"Saved" fades after 2.5s', () => {
    render(<SaveState status="saved" />);
    expect(note()).toHaveTextContent('Saved');

    act(() => { vi.advanceTimersByTime(2499); });
    expect(note()).toHaveTextContent('Saved');
    act(() => { vi.advanceTimersByTime(1); });
    expect(note()).toBeEmptyDOMElement();
  });

  it('"Not saved" never fades', () => {
    render(<SaveState status="error" />);
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(note()).toHaveTextContent('Not saved');
  });

  it('a second save re-shows "Saved" when the key changes, even though status never left "saved"', () => {
    const { rerender } = render(<SaveState status="saved" savedKey={1} />);
    act(() => { vi.advanceTimersByTime(3000); });
    expect(note()).toBeEmptyDOMElement();

    rerender(<SaveState status="saved" savedKey={2} />);
    expect(note()).toHaveTextContent('Saved');
    // …and the new showing gets its own full 2.5s.
    act(() => { vi.advanceTimersByTime(2499); });
    expect(note()).toHaveTextContent('Saved');
    act(() => { vi.advanceTimersByTime(1); });
    expect(note()).toBeEmptyDOMElement();
  });

  it('a re-render with the same key does not re-show a faded "Saved"', () => {
    const { rerender } = render(<SaveState status="saved" savedKey={1} />);
    act(() => { vi.advanceTimersByTime(3000); });

    rerender(<SaveState status="saved" savedKey={1} className="x" />);

    expect(note()).toBeEmptyDOMElement();
  });

  it('saving → saved shows "Saved" again without a key', () => {
    const { rerender } = render(<SaveState status="saved" />);
    act(() => { vi.advanceTimersByTime(3000); });

    rerender(<SaveState status="saving" />);
    expect(note()).toHaveTextContent('Saving…');
    rerender(<SaveState status="saved" />);
    expect(note()).toHaveTextContent('Saved');
  });

  it('a new edit replaces "Saved" at once', () => {
    const { rerender } = render(<SaveState status="saved" />);
    rerender(<SaveState status="pending" />);
    expect(note()).toHaveTextContent('Unsaved changes');
    expect(note()).not.toHaveClass('is-ok');
  });

  it('carries a caller class', () => {
    render(<SaveState status="idle" className="ms-2" />);
    expect(note()).toHaveClass('hr-save-state', 'ms-2');
  });
});

describe('mutationSaveStatus', () => {
  const m = (over: Partial<{ isPending: boolean; isSuccess: boolean; isError: boolean }>) =>
    ({ isPending: false, isSuccess: false, isError: false, ...over });

  it('maps a TanStack mutation to a save status', () => {
    expect(mutationSaveStatus(m({}))).toBe('idle');
    expect(mutationSaveStatus(m({ isPending: true }))).toBe('saving');
    expect(mutationSaveStatus(m({ isSuccess: true }))).toBe('saved');
    expect(mutationSaveStatus(m({ isError: true }))).toBe('error');
  });

  it('in flight wins over a previous outcome', () => {
    expect(mutationSaveStatus(m({ isPending: true, isError: true }))).toBe('saving');
    expect(mutationSaveStatus(m({ isPending: true, isSuccess: true }))).toBe('saving');
  });
});
