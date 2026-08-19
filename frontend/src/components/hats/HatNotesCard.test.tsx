/**
 * Notes are the only free-text field on a hat that a re-analysis cannot touch.
 * Every other prose field here is derived and gets rewritten by a refresh, so
 * the card has to say which one this is — and the save has to behave.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { HatNotesCard } from './HatNotesCard';
import * as hatsApi from '../../api/hats';
import type { HatRead } from '../../types';

vi.mock('../../api/hats', () => ({ updateHat: vi.fn(async () => ({})) }));

function hat(over: Partial<HatRead> = {}): HatRead {
  return {
    id: 5, case_id: null, position_in_case: null, display_id: 'A-001-01',
    case_display_id: 'A-001', case_type: null, photo_path: null,
    original_path: null, thumb_path: null, condition: 'new', date_last_worn: null,
    wear_count: 0, size: 'classic', style: 'a_game', is_beanie: false, colors: [],
    room_id: null, room_name: null, brand: null, logo_detected: null,
    artist_series: null, construction: null, hydrolite: false, hydro: false,
    model_name: null, colorway: null, purchase_price: null, purchased_at: null,
    model_confidence: null, style_descriptor: null, design_notes: null,
    owner_notes: null,
    estimated_new_price: null, estimated_new_price_source: null, resale_price: null,
    resale_price_source: null, resale_price_url: null, resale_checked_at: null,
    resale_price_scope: null, analysis_status: null, analysis_stage: null,
    analysis_job_id: null, analysis_error: null, analyzed_at: null,
    disposed_at: null, disposed_via: null, disposed_price: null, disposed_to: null,
    disposed_notes: null, ebay_avg_price: null, ebay_median_price: null,
    ebay_listing_count: null, ebay_search_url: null, ebay_checked_at: null,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    ...over,
  };
}

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
