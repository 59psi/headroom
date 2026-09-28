/**
 * What a dialog owes the keyboard: Tab stays inside it, in both directions.
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Modal } from './Modal';

function renderModal() {
  render(
    <>
      <button type="button">Behind the dialog</button>
      <Modal title="Edit" onClose={vi.fn()} footer={<button type="button">Save</button>}>
        <input aria-label="Name" />
      </Modal>
    </>,
  );
}

describe('Modal', () => {
  it('wraps Tab from the last control back to the first, never out to the page', async () => {
    const user = userEvent.setup();
    renderModal();
    screen.getByRole('button', { name: 'Save' }).focus();

    await user.tab();

    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Behind the dialog' })).not.toHaveFocus();
  });

  it('wraps Shift+Tab from the first control to the last', async () => {
    const user = userEvent.setup();
    renderModal();
    screen.getByRole('button', { name: 'Close' }).focus();

    await user.tab({ shift: true });

    expect(screen.getByRole('button', { name: 'Save' })).toHaveFocus();
  });

  it('adds a body class for a caller that needs one, beside the base class', () => {
    render(<Modal title="Crop" onClose={vi.fn()} bodyClassName="hr-cropper-body"><p>stage</p></Modal>);
    expect(screen.getByText('stage').parentElement).toHaveClass('modal-body', 'hr-cropper-body');
  });
});
