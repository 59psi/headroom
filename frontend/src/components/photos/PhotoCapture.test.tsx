/**
 * The photo picker: the empty square IS the control, and a dropped image
 * goes through the same cropper a picked one does — Cancel there still means
 * cancel, and only an image is taken.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { PhotoCapture } from './PhotoCapture';

// The real cropper draws on a canvas jsdom does not have; the capture flow
// only needs its three exits.
vi.mock('./PhotoCropper', () => ({
  PhotoCropper: (p: { filename: string; onCancel: () => void; onUseOriginal: () => void }) => (
    <div role="dialog" aria-label={`Crop ${p.filename}`}>
      <button type="button" onClick={p.onCancel}>Cancel</button>
      <button type="button" onClick={p.onUseOriginal}>Use original</button>
    </div>
  ),
}));

const realCreate = URL.createObjectURL;
const realRevoke = URL.revokeObjectURL;

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:photo');
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  URL.createObjectURL = realCreate;
  URL.revokeObjectURL = realRevoke;
});

function drop(target: Element, files: File[]) {
  const dataTransfer = { files, types: ['Files'] };
  fireEvent.dragOver(target, { dataTransfer });
  fireEvent.drop(target, { dataTransfer });
}

const jpeg = (name = 'cap.jpg') => new File([new Uint8Array(4)], name, { type: 'image/jpeg' });

describe('PhotoCapture', () => {
  it('opens the picker from the empty square', async () => {
    const user = userEvent.setup();
    const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {});
    renderWithProviders(<PhotoCapture onCapture={vi.fn()} previewUrl={null} />);

    await user.click(screen.getByRole('button', { name: /Add a photo/ }));
    expect(click).toHaveBeenCalled();
    click.mockRestore();
  });

  it('sends a picked photo through the cropper', async () => {
    const user = userEvent.setup();
    const onCapture = vi.fn();
    renderWithProviders(<PhotoCapture onCapture={onCapture} previewUrl={null} />);

    await user.upload(screen.getByLabelText('Choose a photo'), jpeg());
    await user.click(await screen.findByRole('button', { name: 'Use original' }));
    expect(onCapture).toHaveBeenCalledWith(expect.objectContaining({ name: 'cap.jpg' }));
  });

  it('takes whatever the picker returns, even with no type', async () => {
    // The picker's `accept` already asked the OS for images; a file it hands
    // back with a blank type (an unregistered extension) is still one, and
    // dropping it silently would leave the tap doing nothing at all.
    renderWithProviders(<PhotoCapture onCapture={vi.fn()} previewUrl={null} />);
    fireEvent.change(screen.getByLabelText('Choose a photo'), {
      target: { files: [new File(['x'], 'scan.avif', { type: '' })] },
    });
    expect(await screen.findByRole('dialog', { name: 'Crop scan.avif' })).toBeInTheDocument();
  });

  it('takes a dropped image through the same cropper', async () => {
    const user = userEvent.setup();
    const onCapture = vi.fn();
    renderWithProviders(<PhotoCapture onCapture={onCapture} previewUrl={null} />);

    drop(screen.getByRole('button', { name: /Add a photo/ }), [jpeg('dropped.jpg')]);
    expect(await screen.findByRole('dialog', { name: 'Crop dropped.jpg' })).toBeInTheDocument();

    // Cancel still means cancel: nothing is captured.
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCapture).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('ignores a dropped file that is not an image', () => {
    renderWithProviders(<PhotoCapture onCapture={vi.fn()} previewUrl={null} />);
    drop(screen.getByRole('button', { name: /Add a photo/ }), [
      new File(['x'], 'notes.pdf', { type: 'application/pdf' }),
    ]);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('accepts a HEIC whose type the browser left blank', async () => {
    renderWithProviders(<PhotoCapture onCapture={vi.fn()} previewUrl={null} />);
    drop(screen.getByRole('button', { name: /Add a photo/ }), [new File(['x'], 'IMG_0042.HEIC', { type: '' })]);
    expect(await screen.findByRole('dialog', { name: 'Crop IMG_0042.HEIC' })).toBeInTheDocument();
  });

  it('offers only a replace button when the page shows the photo itself', () => {
    renderWithProviders(<PhotoCapture onCapture={vi.fn()} hidePreview />);
    expect(screen.getByRole('button', { name: 'Replace photo' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Add a photo/ })).not.toBeInTheDocument();
  });
});
