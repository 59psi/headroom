/**
 * Notes are the only free-text field on a hat that a re-analysis cannot touch.
 * Every other prose field here is derived and gets rewritten by a refresh, so
 * the card has to say which one this is — and the save has to behave.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
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

beforeEach(() => vi.clearAllMocks());

describe('HatNotesCard', () => {
  it('seeds the field from the hat', () => {
    renderWithProviders(<HatNotesCard hat={hat({ owner_notes: 'Original.' })} />);
    expect(screen.getByLabelText('Your notes')).toHaveValue('Original.');
  });

  it('cannot be saved until something actually changed', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HatNotesCard hat={hat({ owner_notes: 'Original.' })} />);

    const save = screen.getByRole('button', { name: /save notes/i });
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText('Your notes'), ' More.');
    expect(save).toBeEnabled();
  });

  it('saves what was typed', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HatNotesCard hat={hat()} />);
    await user.type(screen.getByLabelText('Your notes'), 'Bought in Maui.');
    await user.click(screen.getByRole('button', { name: /save notes/i }));
    expect(hatsApi.updateHat).toHaveBeenCalledWith(5, { owner_notes: 'Bought in Maui.' });
  });

  it('sends null rather than an empty string when cleared', async () => {
    // "" would read as a hat that HAS notes which happen to be blank, and that
    // renders and exports differently from one that never had any.
    const user = userEvent.setup();
    renderWithProviders(<HatNotesCard hat={hat({ owner_notes: 'Original.' })} />);
    await user.clear(screen.getByLabelText('Your notes'));
    await user.click(screen.getByRole('button', { name: /save notes/i }));
    expect(hatsApi.updateHat).toHaveBeenCalledWith(5, { owner_notes: null });
  });

  it('says the field survives a refresh', () => {
    renderWithProviders(<HatNotesCard hat={hat()} />);
    expect(screen.getByText(/Never overwritten by an analysis/)).toBeInTheDocument();
  });
});
