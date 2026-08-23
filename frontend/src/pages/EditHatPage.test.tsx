import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../test/utils';
import { EditHatPage } from './EditHatPage';
import * as hatsApi from '../api/hats';
import type { HatRead } from '../types';

/**
 * The Collection / collab field is wired through a `Record<string, unknown>`
 * payload, so `tsc` cannot tell whether the state is actually placed on the
 * request. Forgetting the one payload line would leave a field that accepts
 * typing and silently discards it — invisible to every other check. These
 * tests pin the seed and the submit.
 */

const HAT: HatRead = {
  direct_room_id: null, limited_edition: false,
  id: 7,
  case_id: null,
  position_in_case: null,
  display_id: 'H-007',
  case_display_id: null,
  case_type: null,
  photo_path: null,
  original_path: null,
  thumb_path: null,
  condition: 'new',
  date_last_worn: null,
  wear_count: 0,
  size: 'classic',
  style: 'collab',
  construction: null,
  hydrolite: false,
  hydro: false,
  is_beanie: false,
  colors: [],
  room_id: null,
  room_name: null,
  brand: 'melin',
  logo_detected: null,
  artist_series: 'Skye Walker',
  model_name: 'Coronado',
  colorway: null,
  purchase_price: null,
  purchased_at: null,
  model_confidence: null,
  style_descriptor: null,
  design_notes: null,
  owner_notes: null,
  estimated_new_price: null,
  estimated_new_price_source: null,
  resale_price: null,
  resale_price_source: null,
  resale_price_url: null,
  resale_price_scope: null,
  resale_checked_at: null,
  analysis_status: 'ok',
  analysis_stage: null,
  analysis_job_id: null,
  analysis_error: null,
  analyzed_at: null,
  disposed_at: null,
  disposed_via: null,
  disposed_price: null,
  disposed_to: null,
  disposed_notes: null,
  ebay_avg_price: null,
  ebay_median_price: null,
  ebay_listing_count: null,
  ebay_search_url: null,
  ebay_checked_at: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

vi.mock('../api/hats', () => ({
  getHat: vi.fn(async () => HAT),
  updateHat: vi.fn(async () => HAT),
  uploadHatPhoto: vi.fn(),
  assignHat: vi.fn(),
  updateHatColors: vi.fn(async () => HAT),
  getStyles: vi.fn(async () => [{ value: 'collab', label: 'Collab' }]),
  getSizes: vi.fn(async () => [{ value: 'classic', label: 'Classic' }]),
  getConditions: vi.fn(async () => [{ value: 'new', label: 'New' }]),
  getConstructions: vi.fn(async () => ['HYDRO', 'HYDROLite', 'Thermal']),
  getCollections: vi.fn(async () => ['Piña', 'Skye Walker']),
}));
vi.mock('../api/cases', () => ({ listCases: vi.fn(async () => []) }));
vi.mock('../api/client', () => ({ apiFetch: vi.fn(async () => []) }));
vi.mock('react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router')>()),
  useParams: () => ({ hatId: '7' }),
  useNavigate: () => vi.fn(),
}));

describe('EditHatPage — Collection / collab', () => {
  beforeEach(() => vi.clearAllMocks());

  it('seeds the field from the hat', async () => {
    renderWithProviders(<EditHatPage />);

    expect(await screen.findByLabelText('Collection or collaboration')).toHaveValue('Skye Walker');
  });

  it('submits what was typed as artist_series', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    const field = await screen.findByLabelText('Collection or collaboration');
    await user.clear(field);
    await user.type(field, 'melin x OluKai');
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(hatsApi.updateHat).toHaveBeenCalled());
    expect(vi.mocked(hatsApi.updateHat).mock.calls[0][1]).toMatchObject({
      artist_series: 'melin x OluKai',
    });
  });

  it('clears the field to null rather than an empty string', async () => {
    const user = userEvent.setup();
    renderWithProviders(<EditHatPage />);

    await user.clear(await screen.findByLabelText('Collection or collaboration'));
    await user.click(screen.getByRole('button', { name: 'Save Changes' }));

    await waitFor(() => expect(hatsApi.updateHat).toHaveBeenCalled());
    expect(vi.mocked(hatsApi.updateHat).mock.calls[0][1]).toMatchObject({
      artist_series: null,
    });
  });
});
