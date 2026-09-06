import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ErrorNote, describeError } from './ErrorNote';

describe('ErrorNote', () => {
  it('renders nothing while nothing has failed', () => {
    const { container } = render(<ErrorNote of={{ isError: false, error: null }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the failure as an alert, without the "Error:" prefix String() adds', () => {
    render(<ErrorNote of={{ isError: true, error: new Error('HTTP 500 boom') }} />);
    const note = screen.getByRole('alert');
    expect(note).toHaveTextContent('HTTP 500 boom');
    expect(note).not.toHaveTextContent('Error:');
  });

  it('takes a list and shows the first failure in it', () => {
    render(
      <ErrorNote
        what="Could not save"
        of={[
          { isError: false, error: null },
          { isError: true, error: new Error('disk full') },
          { isError: true, error: new Error('second') },
        ]}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Could not save — disk full');
  });
});

describe('describeError', () => {
  it('unwraps an Error and stringifies anything else', () => {
    expect(describeError(new Error('x'))).toBe('x');
    expect(describeError('plain')).toBe('plain');
    expect(describeError(42)).toBe('42');
  });
});
