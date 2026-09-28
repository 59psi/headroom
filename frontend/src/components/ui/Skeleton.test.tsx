import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Skeleton } from './Skeleton';

/**
 * The bars are decoration; what assistive tech hears is one "Loading…".
 * The shape is the point for everyone else: N lines with a short last one,
 * or a single block the size of what is coming.
 */
function bars(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>('.hr-skeleton'));
}

describe('Skeleton', () => {
  it('announces a single "Loading…" status', () => {
    render(<Skeleton lines={4} />);
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Loading…');
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });

  it('says nothing at all when decorative — hidden, not a second status', () => {
    // A page with four skeletons read "Loading… Loading… Loading… Loading…";
    // all but one are decorative, and decorative means invisible to a reader.
    const { container } = render(<><Skeleton /><Skeleton decorative lines={3} /></>);
    expect(screen.getAllByRole('status')).toHaveLength(1);
    const quiet = container.querySelectorAll('.hr-skeleton-wrap')[1];
    expect(quiet).toHaveAttribute('aria-hidden', 'true');
    expect(quiet).not.toHaveTextContent('Loading');
  });

  it('takes a more specific label', () => {
    render(<Skeleton label="Loading share links…" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading share links…');
  });

  it('draws two lines by default, the last one short like the end of a paragraph', () => {
    const { container } = render(<Skeleton />);
    const lines = bars(container);
    expect(lines).toHaveLength(2);
    expect(lines[0].style.width).toBe('');
    expect(lines[1].style.width).toBe('62%');
  });

  it('draws as many lines as asked', () => {
    const { container } = render(<Skeleton lines={5} />);
    expect(bars(container)).toHaveLength(5);
    expect(bars(container).every(b => b.classList.contains('hr-skeleton-line'))).toBe(true);
  });

  it('a single line runs at the given width, not the short-last-line width', () => {
    const { container } = render(<Skeleton lines={1} width="40%" />);
    const [line] = bars(container);
    expect(line.style.width).toBe('40%');
  });

  it('every bar is hidden from assistive tech', () => {
    const { container } = render(<Skeleton lines={3} />);
    for (const bar of bars(container)) expect(bar).toHaveAttribute('aria-hidden', 'true');
  });

  it('height draws one block of that size instead of lines', () => {
    const { container } = render(<Skeleton height={64} width={120} lines={4} />);
    const all = bars(container);
    expect(all).toHaveLength(1);
    expect(all[0]).not.toHaveClass('hr-skeleton-line');
    expect(all[0].style.height).toBe('64px');
    expect(all[0].style.width).toBe('120px');
  });

  it('carries a caller class on the wrapper', () => {
    render(<Skeleton className="mb-3" />);
    expect(screen.getByRole('status')).toHaveClass('hr-skeleton-wrap', 'mb-3');
  });
});
