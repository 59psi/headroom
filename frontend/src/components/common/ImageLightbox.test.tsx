/**
 * A photo that opens full-screen on tap.
 *
 * The overlay is portalled to <body>: rendered in place, `position: fixed`
 * is measured against any ancestor with a transform, and a "full screen"
 * view that opens confined to a card is the bug that motivated it. The
 * keyboard contract (Escape closes, focus returns to the thumbnail) is what
 * made the thumbnail a real button in the first place.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ImageLightbox } from './ImageLightbox';

function renderInTransformedCard() {
  return render(
    <div className="card" style={{ transform: 'translateY(0)' }} data-testid="card">
      <ImageLightbox src="/uploads/hat.png" alt="Coronado" hat />
    </div>,
  );
}

describe('ImageLightbox', () => {
  it('is a named button that opens a dialog', async () => {
    const user = userEvent.setup();
    renderInTransformedCard();

    await user.click(screen.getByRole('button', { name: 'View Coronado full size' }));

    expect(screen.getByRole('dialog', { name: 'Coronado' })).toBeInTheDocument();
  });

  it('opens outside the card it sits in', async () => {
    const user = userEvent.setup();
    renderInTransformedCard();

    await user.click(screen.getByRole('button', { name: 'View Coronado full size' }));

    const dialog = screen.getByRole('dialog');
    expect(screen.getByTestId('card')).not.toContainElement(dialog);
    expect(dialog.parentElement).toBe(document.body);
  });

  it('closes on Escape and hands focus back to the thumbnail', async () => {
    const user = userEvent.setup();
    renderInTransformedCard();
    const thumb = screen.getByRole('button', { name: 'View Coronado full size' });

    await user.click(thumb);
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(thumb);
  });

  it('closes from its close button', async () => {
    const user = userEvent.setup();
    renderInTransformedCard();

    await user.click(screen.getByRole('button', { name: 'View Coronado full size' }));
    await user.click(screen.getByRole('button', { name: 'Close' }));

    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('falls back to a generic name when the photo has no alt text', () => {
    render(<ImageLightbox src="/uploads/case.jpg" />);
    expect(screen.getByRole('button', { name: 'View photo full size' })).toBeInTheDocument();
  });
});
