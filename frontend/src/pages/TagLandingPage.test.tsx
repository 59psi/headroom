/**
 * Where a hat's QR sticker or NFC tag lands.
 *
 * The feature is only worth having if the tap is genuinely one tap, so what
 * these pin is the state machine around that button: it is there when it
 * should be, gone when the wear is already recorded, and gone when the hat
 * can't be worn at all.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Routes, Route } from 'react-router';
import { renderWithProviders } from '../test/utils';
import { hatFixture } from '../test/fixtures';
import { TagLandingPage } from './TagLandingPage';
import * as hatsApi from '../api/hats';
import type { HatRead } from '../types';

vi.mock('../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    getHat: vi.fn(),
    logWear: vi.fn(async () => ({})),
    undoLatestWear: vi.fn(async () => ({})),
  };
});

const mocked = vi.mocked(hatsApi);

/** The server logs wears against the UTC date, so the page must agree. */
function utcToday() {
  return new Date().toISOString().slice(0, 10);
}

function renderTag(hat: HatRead | Error, id = 5) {
  if (hat instanceof Error) mocked.getHat.mockRejectedValue(hat);
  else mocked.getHat.mockResolvedValue(hat);
  return renderWithProviders(
    <Routes>
      <Route path="/t/h/:hatId" element={<TagLandingPage />} />
    </Routes>,
    { route: `/t/h/${id}` },
  );
}

beforeEach(() => vi.clearAllMocks());

describe('TagLandingPage', () => {
  it('identifies the hat so you can see you scanned the right one', async () => {
    renderTag(hatFixture({ model_name: 'Coronado', colorway: 'Heather Ocean' }));
    expect(await screen.findByText('Coronado')).toBeInTheDocument();
    expect(screen.getByText(/Heather Ocean/)).toBeInTheDocument();
  });

  it('logs the wear in one tap', async () => {
    const user = userEvent.setup();
    renderTag(hatFixture({ model_name: 'Coronado' }));

    await user.click(await screen.findByRole('button', { name: /wore it today/i }));

    await waitFor(() => expect(mocked.logWear).toHaveBeenCalledWith(5));
  });

  it('does not offer to log a wear that is already recorded', async () => {
    renderTag(hatFixture({ model_name: 'Coronado', date_last_worn: utcToday() }));

    expect(await screen.findByText(/worn today/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /wore it today/i })).toBeNull();
    // Undo is the escape hatch for a mis-tap, which a physical tag invites.
    expect(screen.getByRole('button', { name: /undo/i })).toBeInTheDocument();
  });

  it('refuses to log a wear against a hat that has left the collection', async () => {
    renderTag(hatFixture({ model_name: 'Departed', disposed_at: '2026-01-02T00:00:00Z' }));

    expect(await screen.findByText(/left the collection/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /wore it today/i })).toBeNull();
  });

  it('explains itself when the tag names a hat that no longer exists', async () => {
    renderTag(new Error('404'));
    expect(await screen.findByText(/tag not recognized/i)).toBeInTheDocument();
  });

  it('does not call the API for a tag with a non-numeric id', async () => {
    renderTag(hatFixture(), 'nonsense' as unknown as number);
    expect(await screen.findByText(/tag not recognized/i)).toBeInTheDocument();
    expect(mocked.getHat).not.toHaveBeenCalled();
  });

  it('shows the wear as logged the moment it is tapped, before the server answers', async () => {
    // Optimistic: the answer is predictable, and at the closet door a
    // "Logging…" that lasts as long as the Pi takes reads as a tap that
    // didn't take.
    const user = userEvent.setup();
    mocked.logWear.mockReturnValueOnce(new Promise(() => {}));
    renderTag(hatFixture({ model_name: 'Coronado', wear_count: 4 }));

    await user.click(await screen.findByRole('button', { name: /wore it today/i }));

    expect(screen.getByText(/worn today/i)).toBeInTheDocument();
    expect(screen.getByText(/Worn 5 times/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /wore it today/i })).toBeNull();
  });

  it('keeps Undo disabled until the wear it would undo has landed', async () => {
    // An undo sent while the log is still in flight would delete the
    // PREVIOUS wear on the server instead.
    const user = userEvent.setup();
    mocked.logWear.mockReturnValueOnce(new Promise(() => {}));
    renderTag(hatFixture({ model_name: 'Coronado' }));

    await user.click(await screen.findByRole('button', { name: /wore it today/i }));

    expect(screen.getByRole('button', { name: /undo/i })).toBeDisabled();
  });

  it('snaps back to the button, with the reason, when the wear fails', async () => {
    const user = userEvent.setup();
    mocked.logWear.mockRejectedValueOnce(new Error('Hat is disposed'));
    renderTag(hatFixture({ model_name: 'Coronado', wear_count: 4 }));
    await screen.findByRole('button', { name: /wore it today/i });
    // The follow-up refetch never lands, so what is on screen afterwards is
    // the rollback's doing alone — not the server quietly correcting it.
    mocked.getHat.mockReturnValue(new Promise(() => {}));

    await user.click(screen.getByRole('button', { name: /wore it today/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Hat is disposed');
    expect(screen.getByRole('button', { name: /wore it today/i })).toBeInTheDocument();
    expect(screen.queryByText(/worn today/i)).toBeNull();
    expect(screen.getByText(/Worn 4 times/)).toBeInTheDocument();
  });

  it('confirms a logged wear with a toast', async () => {
    const user = userEvent.setup();
    renderTag(hatFixture({ model_name: 'Coronado' }));

    await user.click(await screen.findByRole('button', { name: /wore it today/i }));

    expect(await screen.findByText('Wear logged')).toBeInTheDocument();
  });

  it('undoes a wear and confirms it', async () => {
    const user = userEvent.setup();
    renderTag(hatFixture({ model_name: 'Coronado', date_last_worn: utcToday(), wear_count: 1 }));
    // The refetch after the undo returns the hat as the server now has it.
    mocked.getHat.mockResolvedValue(hatFixture({ model_name: 'Coronado', date_last_worn: null, wear_count: 0 }));

    await user.click(await screen.findByRole('button', { name: /undo/i }));

    await waitFor(() => expect(mocked.undoLatestWear).toHaveBeenCalledWith(5));
    expect(await screen.findByText('Wear undone')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /wore it today/i })).toBeInTheDocument();
  });

  it('holds the page shape while the hat loads', () => {
    mocked.getHat.mockReturnValue(new Promise(() => {}));
    renderWithProviders(
      <Routes><Route path="/t/h/:hatId" element={<TagLandingPage />} /></Routes>,
      { route: '/t/h/5' },
    );
    expect(screen.getByRole('status')).toHaveTextContent('Loading…');
  });
});
