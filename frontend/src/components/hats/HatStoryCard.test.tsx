/**
 * The write-up and the notes look alike on screen and behave nothing alike:
 * one is rewritten by every refresh, the other is the only field on a hat that
 * no automated path touches. These pin the parts that make that legible.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import { HatStoryCard } from './HatStoryCard';
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
    story: null, story_generated_at: null, story_pending: false, owner_notes: null,
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

describe('HatStoryCard', () => {
  it('renders the write-up as separate paragraphs', () => {
    renderWithProviders(
      <HatStoryCard hat={hat({ story: 'First para.\n\nSecond para.' })} />,
    );
    expect(screen.getByText('First para.')).toBeInTheDocument();
    expect(screen.getByText('Second para.')).toBeInTheDocument();
  });

  it('says who wrote it, because the app has no web access to check against', () => {
    renderWithProviders(<HatStoryCard hat={hat({ story: 'Something.' })} />);
    expect(screen.getByText(/Written by Claude/)).toBeInTheDocument();
  });

  it('shows a rewriting badge while one is queued', () => {
    renderWithProviders(<HatStoryCard hat={hat({ story_pending: true })} />);
    expect(screen.getByText('rewriting…')).toBeInTheDocument();
  });

  it('explains how to get one when there is none', () => {
    renderWithProviders(<HatStoryCard hat={hat()} />);
    expect(screen.getByText(/set this hat’s collection/)).toBeInTheDocument();
  });

  it('saves notes and cannot be saved while unchanged', async () => {
    const user = userEvent.setup();
    renderWithProviders(<HatStoryCard hat={hat({ owner_notes: 'Original.' })} />);

    const save = screen.getByRole('button', { name: /save notes/i });
    expect(save).toBeDisabled();  // nothing typed yet

    await user.clear(screen.getByLabelText('Your notes'));
    await user.type(screen.getByLabelText('Your notes'), 'Changed.');
    expect(save).toBeEnabled();

    await user.click(save);
    expect(hatsApi.updateHat).toHaveBeenCalledWith(5, { owner_notes: 'Changed.' });
  });

  it('sends null rather than an empty string when the notes are cleared', async () => {
    // "" would read as a hat that has notes, which happen to be blank —
    // the field renders and exports differently from one that was never used.
    const user = userEvent.setup();
    renderWithProviders(<HatStoryCard hat={hat({ owner_notes: 'Original.' })} />);
    await user.clear(screen.getByLabelText('Your notes'));
    await user.click(screen.getByRole('button', { name: /save notes/i }));
    expect(hatsApi.updateHat).toHaveBeenCalledWith(5, { owner_notes: null });
  });

  it('states that notes survive a refresh', () => {
    renderWithProviders(<HatStoryCard hat={hat()} />);
    expect(screen.getByText(/Never overwritten by an analysis/)).toBeInTheDocument();
  });
});
