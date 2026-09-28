/**
 * Notes are the only free-text field on a hat that a re-analysis cannot touch.
 * Every other prose field here is derived and gets rewritten by a refresh, so
 * the card has to say which one this is — and the save has to behave.
 *
 * It saves itself now (the Save button is gone), so these pin the autosave:
 * nothing is sent until something really changed, what is sent is exactly
 * what was typed (null when cleared), ⌘/Ctrl+Enter and leaving the field
 * save at once, and a failed save says so in place and can be retried.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { hatFixture } from '../../test/fixtures';
import { HatNotesCard } from './HatNotesCard';
import * as hatsApi from '../../api/hats';

vi.mock('../../api/hats', async (importOriginal) => {
  const { stubAll } = await import('../../test/stubModule');
  return {
    ...stubAll(await importOriginal<object>()),
    updateHat: vi.fn(async () => ({}))
  };
});

const hat = hatFixture;
const updateHat = vi.mocked(hatsApi.updateHat);

beforeEach(() => {
  vi.clearAllMocks();
  updateHat.mockImplementation(async () => hatFixture());
});

describe('HatNotesCard', () => {
  it('seeds the field from the hat', () => {
    renderWithProviders(<HatNotesCard hat={hat({ owner_notes: 'Original.' })} />);
    expect(screen.getByLabelText('Your notes')).toHaveValue('Original.');
  });

  it('saves on its own once typing stops, and says so', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HatNotesCard hat={hat()} />);
    await user.type(screen.getByLabelText('Your notes'), 'Bought in Maui.');

    // Not per keystroke — the debounce collapses the typing into one save.
    await waitFor(() => expect(updateHat).toHaveBeenCalledTimes(1), { timeout: 3000 });
    expect(updateHat).toHaveBeenCalledWith(5, { owner_notes: 'Bought in Maui.' });
    expect(await screen.findByText('Saved')).toBeInTheDocument();
  });

  it('saves immediately on ⌘/Ctrl+Enter, without waiting out the debounce', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HatNotesCard hat={hat()} />);
    const field = screen.getByLabelText('Your notes');
    await user.type(field, 'Gift from Sam.');
    await user.keyboard('{Control>}{Enter}{/Control}');

    await waitFor(() => expect(updateHat).toHaveBeenCalledWith(5, { owner_notes: 'Gift from Sam.' }), { timeout: 500 });
    // The shortcut saves; it does not also type a newline into the note.
    expect(field).toHaveValue('Gift from Sam.');
  });

  it('saves when you leave the field', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HatNotesCard hat={hat()} />);
    await user.type(screen.getByLabelText('Your notes'), 'Worn at the wedding.');
    await user.tab();

    await waitFor(() => expect(updateHat).toHaveBeenCalledWith(5, { owner_notes: 'Worn at the wedding.' }), { timeout: 500 });
  });

  it('sends null rather than an empty string when cleared', async () => {
    // "" would read as a hat that HAS notes which happen to be blank, and that
    // renders and exports differently from one that never had any.
    const user = userEvent.setup();
    renderWithProviders(<HatNotesCard hat={hat({ owner_notes: 'Original.' })} />);
    await user.clear(screen.getByLabelText('Your notes'));
    await user.tab();
    await waitFor(() => expect(updateHat).toHaveBeenCalledWith(5, { owner_notes: null }), { timeout: 500 });
  });

  it('sends nothing when the note ends up unchanged', async () => {
    // Typed and then put back: nothing to store, so nothing is sent — the old
    // Save button stayed disabled for the same reason. Trailing whitespace
    // counts as unchanged too; the save trims it anyway.
    const user = userEvent.setup();
    renderWithProviders(<HatNotesCard hat={hat({ owner_notes: 'Original.' })} />);
    const field = screen.getByLabelText('Your notes');
    await user.type(field, ' More.');
    await user.type(field, '{Backspace>6/}');
    await user.type(field, ' ');
    await user.tab();

    await new Promise(r => setTimeout(r, 1200));
    expect(updateHat).not.toHaveBeenCalled();
  });

  it('says a failed save failed, in place, and retries on request', async () => {
    const user = userEvent.setup();
    updateHat.mockRejectedValueOnce(new Error('database is locked'));
    renderWithProviders(<HatNotesCard hat={hat()} />);
    await user.type(screen.getByLabelText('Your notes'), 'Keep.');
    await user.tab();

    expect(await screen.findByText(/database is locked/)).toBeInTheDocument();
    expect(screen.getByText('Not saved')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(updateHat).toHaveBeenCalledTimes(2));
    expect(updateHat).toHaveBeenLastCalledWith(5, { owner_notes: 'Keep.' });
    await waitFor(() => expect(screen.queryByText(/database is locked/)).not.toBeInTheDocument());
  });

  it('says the field survives a refresh', () => {
    renderWithProviders(<HatNotesCard hat={hat()} />);
    expect(screen.getByText(/Never overwritten by an analysis/)).toBeInTheDocument();
  });
});
