import type { CaseRead, HatRead } from '../types';

/**
 * A fully-populated `HatRead` with everything null/zero, for tests to override.
 *
 * `HatRead` has ~50 fields and TypeScript requires all of them, so every test
 * that needs a hat was otherwise obliged to write the whole literal out. That
 * is not just tedious — it means adding a column breaks every test file at
 * once, and each copy drifts in what it considers a "default" hat.
 */
export function hatFixture(over: Partial<HatRead> = {}): HatRead {
  return {
    id: 5, case_id: null, position_in_case: null, display_id: 'A-001-01',
    direct_room_id: null, limited_edition: false,
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
    resale_price_scope: null, analysis_status: null, analysis_stage: null, analysis_stage_at: null,
    analysis_job_id: null, analysis_error: null, analyzed_at: null,
    disposed_at: null, disposed_via: null, disposed_price: null, disposed_to: null,
    disposed_notes: null, ebay_avg_price: null, ebay_median_price: null,
    ebay_listing_count: null, ebay_search_url: null, ebay_checked_at: null,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    ...over,
  };
}


/** Idle sweep progress — what the server sends when nothing is running.
 *
 *  Shared rather than rebuilt per test file: two byte-identical copies of this
 *  shape already existed, so adding a field to `SweepProgress` would have
 *  broken each independently — the exact failure this module exists to stop.
 */
export function sweepProgressFixture(
  over: Partial<import('../types').SweepProgress> = {},
): import('../types').SweepProgress {
  return {
    running: false, done: 0, total: 0, label: null,
    started_at: null, finished_at: null, error: null, pct: 0,
    ...over,
  };
}


/**
 * A fully-populated `CaseRead` — an empty archive case in the default room.
 *
 * Two test files carried their own copy of this literal (`HatFormFields.test`,
 * `RoomDetailPage.test`), one of them captioned "Real payload shape" while
 * missing five fields pydantic always serializes. One copy, typed, so a new
 * `CaseRead` field breaks exactly here.
 */
export function caseFixture(over: Partial<CaseRead> = {}): CaseRead {
  return {
    id: 1, case_type: 'archive', sequence_number: 1, display_id: 'A-001',
    capacity: null, retail_price: 49, hat_count: 0, beanie_count: 0, regular_count: 0,
    room_id: 1, room_name: 'Default Room', hat_thumbs: [], overfull: false,
    nominal_capacity: 3, nominal_regular: 3, nominal_beanie: 6,
    accepts_regular: true, accepts_beanie: true, free_regular: 3, free_beanie: 6,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    ...over,
  };
}
