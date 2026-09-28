import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ErrorBoundary } from './ErrorBoundary';

function Bomb({ explode }: { explode: boolean }) {
  if (explode) throw new TypeError('cannot read properties of undefined');
  return <p>Fine now</p>;
}

afterEach(() => vi.restoreAllMocks());

describe('ErrorBoundary', () => {
  it('replaces a crashed render with what crashed, its stack, and two ways out', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<ErrorBoundary><Bomb explode /></ErrorBoundary>);

    const panel = screen.getByRole('alert');
    expect(panel).toHaveTextContent('App crashed during render');
    expect(panel).toHaveTextContent('TypeError: cannot read properties of undefined');
    expect(screen.getByRole('button', { name: 'Hard reload' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    // Styled by the stylesheet like everything else — no inline palette.
    expect(panel.querySelectorAll('[style]')).toHaveLength(0);
    expect(panel).not.toHaveAttribute('style');
  });

  it('renders the children again after "Try again" once the cause is gone', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const user = userEvent.setup();
    // Outside React: the crashed subtree's own state is gone with it.
    const cause = { present: true };
    function Harness() {
      return <Bomb explode={cause.present} />;
    }
    render(<ErrorBoundary><Harness /></ErrorBoundary>);
    expect(screen.getByRole('alert')).toBeInTheDocument();

    cause.present = false;
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByText('Fine now')).toBeInTheDocument();
  });
});
