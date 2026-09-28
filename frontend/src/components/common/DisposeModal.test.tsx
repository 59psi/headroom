/**
 * Marking a hat disposed: the kind is one tap (chips, not a select), the
 * price field exists only for the kinds that have one, and a price typed
 * under "Sold" does not ride along when the choice changes to "Gifted".
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { hatFixture } from '../../test/fixtures';
import { DisposeModal, dispositionLabel } from './DisposeModal';
import * as hatsApi from '../../api/hats';

vi.mock('../../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return { ...stubAll(await importOriginal<object>()) };
});

const mocked = vi.mocked(hatsApi);

beforeEach(() => {
  vi.clearAllMocks();
  mocked.disposeHat.mockResolvedValue(hatFixture());
});

describe('DisposeModal', () => {
  it('defaults to Sold and sends the price and buyer', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderWithProviders(<DisposeModal hatId={5} show onClose={onClose} />);

    expect(screen.getByRole('button', { name: 'Sold' })).toHaveAttribute('aria-pressed', 'true');
    await user.type(screen.getByLabelText('Price ($)'), '45');
    await user.type(screen.getByLabelText('Buyer or counterparty'), 'Mercari');
    await user.click(screen.getByRole('button', { name: 'Mark as sold' }));

    await waitFor(() => expect(mocked.disposeHat).toHaveBeenCalledWith(5, {
      via: 'sold', price: 45, to: 'Mercari', notes: null,
    }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(screen.getByText('Marked as sold')).toBeInTheDocument();
  });

  it('hides the price for a gift — and does not send one typed earlier', async () => {
    const user = userEvent.setup();
    renderWithProviders(<DisposeModal hatId={5} show onClose={vi.fn()} />);

    await user.type(screen.getByLabelText('Price ($)'), '45');
    await user.click(screen.getByRole('button', { name: 'Gifted' }));

    expect(screen.queryByLabelText('Price ($)')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Recipient or place')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Mark as gifted' }));

    await waitFor(() => expect(mocked.disposeHat).toHaveBeenCalled());
    expect(mocked.disposeHat.mock.calls[0][1]).toMatchObject({ via: 'gifted', price: null });
  });

  it('renders nothing while closed', () => {
    const { container } = renderWithProviders(<DisposeModal hatId={5} show={false} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('names each stored kind in words', () => {
    expect(dispositionLabel('trade')).toBe('Traded');
    expect(dispositionLabel('sold')).toBe('Sold');
    // A kind this build does not know still reads as a word, not a column.
    expect(dispositionLabel('donated')).toBe('Donated');
    expect(dispositionLabel(null)).toBe('Disposed');
  });
});
