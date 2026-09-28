/**
 * One status message, said once.
 *
 * The spinner used to carry a visually-hidden "Loading…" for screen readers
 * AND a visible uppercase "LOADING…" under it, so assistive tech read the
 * same word twice. The visible label is now the status message itself.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LoadingSpinner } from './LoadingSpinner';

describe('LoadingSpinner', () => {
  it('announces "Loading…" once, as a status', () => {
    render(<LoadingSpinner />);
    expect(screen.getByRole('status')).toHaveTextContent(/^Loading…$/);
    expect(screen.getAllByText('Loading…')).toHaveLength(1);
  });

  it('keeps its label prop', () => {
    render(<LoadingSpinner label="Searching" />);
    expect(screen.getByRole('status')).toHaveTextContent(/^Searching…$/);
  });
});
