import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { ToastProvider, useToast, type ToastApi } from './Toast';

/**
 * Toasts acknowledge outcomes the page already renders, so the properties
 * that matter are the ones a person notices when they break: the right role
 * (an error interrupts a screen reader, a "Saved" waits its turn), that they
 * go away on their own — but not while being read — and that a burst of saves
 * never stacks a column of them over the page.
 *
 * Fake timers throughout, driven with `fireEvent` rather than user-event:
 * the durations are the behavior under test, and user-event's own internal
 * delays would need the fake clock threaded through every call.
 */
let toast: ToastApi;
function Capture() {
  toast = useToast();
  return null;
}

function setup() {
  return render(
    <ToastProvider>
      <Capture />
    </ToastProvider>,
  );
}

function region() {
  return screen.getByRole('region', { name: 'Notifications' });
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

describe('ToastProvider', () => {
  it('mounts its live region before the first toast, so the first one is announced', () => {
    setup();
    // A live region only announces changes to a region that already existed.
    // The landmark role alone is not live — `role="region"` has no implicit
    // aria-live — and a `role="status"` toast inserted already holding its
    // text is exactly the change screen readers skip, so the always-mounted
    // container must itself be polite-live.
    expect(region()).toBeEmptyDOMElement();
    expect(region()).toHaveAttribute('aria-live', 'polite');
  });

  it('announces success and info through the polite container, error as an interrupting alert', () => {
    setup();
    act(() => {
      toast.success('Key saved');
      toast.info('Backup started');
      toast.error('Upload failed');
    });

    const r = region();
    // No live region of their own inside the live container — nested live
    // regions double-announce. The nearest `[role]` above them is the region.
    expect(within(r).getByText('Key saved').closest('[role]')).toBe(r);
    expect(within(r).getByText('Backup started').closest('[role]')).toBe(r);
    expect(within(r).getAllByRole('alert')).toHaveLength(1);
    expect(within(r).getByRole('alert')).toHaveTextContent('Upload failed');
    expect(within(r).getByText('Key saved').closest('.hr-toast')).toHaveClass('is-success');
    expect(within(r).getByText('Upload failed').closest('.hr-toast')).toHaveClass('is-error');
    expect(within(r).getByText('Backup started').closest('.hr-toast')).toHaveClass('is-info');
  });

  it('dismisses a success after 3.5s', () => {
    setup();
    act(() => toast.success('Key saved'));

    act(() => { vi.advanceTimersByTime(3499); });
    expect(screen.getByText('Key saved')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(1); });
    expect(screen.queryByText('Key saved')).not.toBeInTheDocument();
  });

  it('keeps an error up twice as long (7s) — it is the one worth reading', () => {
    setup();
    act(() => toast.error('Upload failed'));

    act(() => { vi.advanceTimersByTime(6999); });
    expect(screen.getByText('Upload failed')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(1); });
    expect(screen.queryByText('Upload failed')).not.toBeInTheDocument();
  });

  it('honors an explicit duration', () => {
    setup();
    act(() => toast.info('Quick', { duration: 1000 }));
    act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.queryByText('Quick')).not.toBeInTheDocument();
  });

  it('holds still while hovered or focused, and resumes after', () => {
    setup();
    act(() => toast.success('Link revoked', { action: { label: 'Undo', onClick: () => {} } }));
    const el = screen.getByText('Link revoked').closest('.hr-toast')!;

    fireEvent.mouseEnter(el);
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(screen.getByText('Link revoked')).toBeInTheDocument();

    fireEvent.mouseLeave(el);
    // Keyboard users reach the action button the same way: focus pauses too.
    fireEvent.focus(screen.getByRole('button', { name: 'Undo' }));
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(screen.getByText('Link revoked')).toBeInTheDocument();

    fireEvent.blur(screen.getByRole('button', { name: 'Undo' }));
    act(() => { vi.advanceTimersByTime(3500); });
    expect(screen.queryByText('Link revoked')).not.toBeInTheDocument();
  });

  it('shows at most three: the oldest falls off a burst', () => {
    setup();
    act(() => {
      toast.success('One');
      toast.success('Two');
      toast.success('Three');
      toast.success('Four');
    });

    expect(screen.queryByText('One')).not.toBeInTheDocument();
    for (const m of ['Two', 'Three', 'Four']) expect(screen.getByText(m)).toBeInTheDocument();
    // Newest last, so the stack reads top-to-bottom in the order it happened.
    const order = Array.from(region().querySelectorAll('.hr-toast-msg')).map(n => n.textContent);
    expect(order).toEqual(['Two', 'Three', 'Four']);
  });

  it('a surviving toast keeps its own clock when an older one is evicted', () => {
    setup();
    act(() => toast.success('Two'));
    act(() => { vi.advanceTimersByTime(2000); });
    act(() => {
      toast.success('Three');
      toast.success('Four');
      toast.success('Five');
    });
    // 'Two' was evicted by the burst; 'Three' started 0ms ago and must not
    // inherit the evicted toast's elapsed time.
    act(() => { vi.advanceTimersByTime(1600); });
    expect(screen.getByText('Three')).toBeInTheDocument();
  });

  it('runs the action once and dismisses the toast', () => {
    setup();
    const onClick = vi.fn();
    act(() => toast.success('Hat disposed', { action: { label: 'Undo', onClick } }));

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));

    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Hat disposed')).not.toBeInTheDocument();
  });

  it('the close button dismisses without waiting', () => {
    setup();
    act(() => toast.error('Upload failed'));

    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }));

    expect(screen.queryByText('Upload failed')).not.toBeInTheDocument();
  });

  it('hands out the same API object across provider re-renders', () => {
    // Callers put `toast` in effect and callback deps; a fresh object per
    // render would re-run those effects every time a toast appears.
    const { rerender } = setup();
    const first = toast;
    act(() => toast.success('Saved'));
    rerender(
      <ToastProvider>
        <Capture />
      </ToastProvider>,
    );
    expect(toast).toBe(first);
  });
});

describe('useToast outside a provider', () => {
  it('is a silent no-op rather than a throw', () => {
    render(<Capture />);
    expect(() => {
      toast.success('Saved');
      toast.error('Failed');
      toast.info('Note', { action: { label: 'View', onClick: () => {} } });
    }).not.toThrow();
    expect(screen.queryByText('Saved')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Notifications' })).not.toBeInTheDocument();
  });
});
