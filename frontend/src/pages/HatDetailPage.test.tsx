/**
 * `A-029-01` reads as "hat 01 of case A-029", so the case part of it is a
 * breadcrumb and people tap it expecting to land on the case. The "View Case"
 * button exists but sits below the identification card, the photo and the
 * specs — a long scroll back to where you just came from.
 */
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../test/utils';
import { HatHeadingId } from './HatDetailPage';
import type { HatRead } from '../types';

function hat(over: Partial<HatRead> = {}): HatRead {
  return {
    id: 12, case_id: 3, position_in_case: 1,
    display_id: 'A-029-01', case_display_id: 'A-029', case_type: 'daily_wear',
    photo_path: null, original_path: null, thumb_path: null,
    condition: 'new_with_tags', date_last_worn: null, wear_count: 0,
    size: 'classic', style: 'compass', is_beanie: false, colors: [],
    room_id: 1, room_name: "Brandon's Closet", brand: 'Melin',
    logo_detected: null, artist_series: null, construction: 'HYDRO',
    hydrolite: false, hydro: true, model_name: 'Compass Hydro', colorway: null,
    purchase_price: null, purchased_at: null, model_confidence: null,
    style_descriptor: null, design_notes: null, estimated_new_price: null,
    owner_notes: null,
    estimated_new_price_source: null, resale_price: null,
    resale_price_source: null, resale_price_url: null, resale_checked_at: null,
    resale_price_scope: null, analysis_status: 'ok', analysis_stage: null,
    analysis_job_id: null, analysis_error: null, analyzed_at: null,
    disposed_at: null, disposed_via: null, disposed_price: null,
    disposed_to: null, disposed_notes: null, ebay_avg_price: null,
    ebay_median_price: null, ebay_listing_count: null, ebay_search_url: null,
    ebay_checked_at: null, created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...over,
  };
}

describe('HatHeadingId', () => {
  it('links the case part of the id to that case', () => {
    renderWithProviders(<HatHeadingId hat={hat()} />);
    const link = screen.getByRole('link', { name: 'A-029' });
    expect(link).toHaveAttribute('href', '/cases/A-029');
  });

  it('keeps the position suffix out of the link', () => {
    // Tapping the "-01" is not a request to go to the case, and the whole
    // heading being one link would hide which part is the case.
    renderWithProviders(<HatHeadingId hat={hat()} />);
    expect(screen.getByRole('link', { name: 'A-029' })).toBeInTheDocument();
    expect(screen.getByText(/-01/)).toBeInTheDocument();
  });

  it('renders the full id, not just the case', () => {
    const { container } = renderWithProviders(<HatHeadingId hat={hat()} />);
    expect(container.textContent).toBe('A-029-01');
  });

  it('offers no link for a hat that is not in a case', () => {
    renderWithProviders(
      <HatHeadingId hat={hat({ case_display_id: null, display_id: null })} />,
    );
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText('Hat #12')).toBeInTheDocument();
  });

  it('does not dress a mismatched id up as navigation', () => {
    // The suffix is sliced off `display_id` on the assumption the server built
    // it from the case id. If that ever stops being true, render plain text
    // rather than a link to a case this hat may not be in.
    renderWithProviders(
      <HatHeadingId hat={hat({ display_id: 'LEGACY-7', case_display_id: 'A-029' })} />,
    );
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText('LEGACY-7')).toBeInTheDocument();
  });
});
