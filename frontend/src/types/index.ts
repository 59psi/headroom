export interface ColorTag {
  color_name: string;
  general_color: string;
  hex_value: string;
  dominance_rank: number;
  tier?: string;
}

export interface HatSummary {
  id: number;
  display_id: string | null;
  style: string;
  is_beanie: boolean;
  photo_path: string | null;
  thumb_path: string | null;
}

export interface CaseRead {
  id: number;
  case_type: 'archive' | 'daily_wear';
  sequence_number: number;
  display_id: string;
  photo_path: string | null;
  capacity: number | null;
  hat_count: number;
  beanie_count: number;
  regular_count: number;
  room_id: number;
  room_name: string;
  /** Computed server-side from the same rule the write path enforces, so the
   *  picker can't disagree with what a save will accept. */
  /** Up to 4 hat photos for the collage the Cases grid renders. */
  hat_thumbs: string[];
  /** Past nominal capacity — a 4th hat in a 3-hat case. Allowed, but shown. */
  overfull: boolean;
  /** The count at which this case reads as FULL (per-case override aware). */
  nominal_capacity: number;
  accepts_regular: boolean;
  accepts_beanie: boolean;
  free_regular: number;
  free_beanie: number;
  created_at: string;
  updated_at: string;
}

export interface CaseDetail extends CaseRead {
  hats: HatSummary[];
}

export interface HatRead {
  id: number;
  case_id: number | null;
  position_in_case: number | null;
  display_id: string | null;
  case_display_id: string | null;
  case_type: 'archive' | 'daily_wear' | null;
  photo_path: string | null;
  original_path: string | null;
  thumb_path: string | null;
  condition: string;
  date_last_worn: string | null;
  wear_count: number;
  size: string;
  style: string;
  is_beanie: boolean;
  colors: ColorTag[];
  room_id: number | null;
  room_name: string | null;

  // AI / pricing
  brand: string | null;
  logo_detected: string | null;
  artist_series: string | null;
  /** Free-form construction ("HYDRO", "HYDROLite", "Thermal", …). */
  construction: string | null;
  /** Derived from `construction` server-side — read-only here. */
  hydrolite: boolean;
  hydro: boolean;
  model_name: string | null;
  colorway: string | null;
  purchase_price: number | null;
  purchased_at: string | null;
  model_confidence: string | null;
  style_descriptor: string | null;
  design_notes: string | null;
  estimated_new_price: number | null;
  estimated_new_price_source: string | null;
  resale_price: number | null;
  resale_price_source: string | null;
  resale_price_url: string | null;
  resale_checked_at: string | null;
  /** What `resale_price` is a price OF — see `lib/valuation.ts`.
   *  "manual" (a person typed it) · "model" (comparable listings for this
   *  model) · "category" (every listing in the style category — a price level,
   *  not this hat's value) · null (no price). */
  resale_price_scope: 'manual' | 'model' | 'category' | null;
  analysis_status: string | null;
  analysis_stage: string | null;
  analysis_job_id: number | null;
  analysis_error: string | null;
  analyzed_at: string | null;

  // v0.3 disposition
  disposed_at: string | null;
  disposed_via: string | null;
  disposed_price: number | null;
  disposed_to: string | null;
  disposed_notes: string | null;

  // v0.4 eBay
  ebay_avg_price: number | null;
  ebay_median_price: number | null;
  ebay_listing_count: number | null;
  ebay_search_url: string | null;
  ebay_checked_at: string | null;

  created_at: string;
  updated_at: string;
}

export interface ImportJobItem {
  id: number;
  filename: string;
  status: 'queued' | 'processing' | 'done' | 'error' | 'skipped' | 'cancelled';
  hat_id: number | null;
  error: string | null;
  bytes: number;
}

export interface ImportJob {
  id: number;
  created_at: string;
  finished_at: string | null;
  total: number;
  done: number;
  errors: number;
  skipped: number;
  status: 'queued' | 'running' | 'done' | 'cancelled';
  items: ImportJobItem[];
}

export interface ActivityRow {
  id: number;
  occurred_at: string;
  kind: string;
  entity_type: string;
  entity_id: number | null;
  summary: string;
  details: string | null;
}

export interface EbayCredsStatus {
  configured: boolean;
  app_id_masked: string | null;
  marketplace: string;
  detected_env: 'production' | 'sandbox' | 'unknown' | null;
}

export interface SearchResult {
  id: number;
  display_id: string | null;
  case_display_id: string | null;
  photo_path: string | null;
  thumb_path: string | null;
  style: string;
  condition: string;
  size: string;
  is_beanie: boolean;
  brand: string | null;
  model_name: string | null;
  colors: ColorTag[];
  room_id: number | null;
  room_name: string | null;
}

export interface ColorSearchResult extends SearchResult {
  matched_hex: string;
  distance: number;
}

export interface PaletteColor {
  name: string;
  hex: string;
}

export interface MetaOption {
  value: string;
  label: string;
}

export interface RoomRead {
  id: number;
  name: string;
  case_count: number;
  /** Exactly one room is the default: the fallback for orphaned cases and the
   *  room new cases land in. It's the only room that can't be deleted. */
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface ApiKeyStatus {
  configured: boolean;
  source: string | null;
  masked: string | null;
}

export interface ApiKeyTestResult {
  ok: boolean;
  detail: string;
}

export interface MdnsStatus {
  enabled: boolean;
  advertising: boolean;
  hostname: string;
  port: number;
  ip: string | null;
  url: string | null;
  error: string | null;
}

export interface ModelStatus {
  model_id: string;
  source: 'database' | 'environment' | 'default';
}

export interface RecentError {
  hat_id: number;
  display_id: string | null;
  analysis_error: string | null;
  analyzed_at: string | null;
  photo_path: string | null;
}

export interface BackupInfo {
  filename: string;
  size_bytes: number;
  created_at: string;
}

/** One hat waiting in the analysis queue. Mirrors `PendingHat` in schemas/admin.py. */
export interface PendingHat {
  id: number;
  display_id: string | null;
  label: string | null;
  stage: string | null;
  photo_path: string | null;
}

/** A bulk re-analysis run. Progress is derived server-side, never accumulated. */
export interface AnalysisJobRead {
  id: number;
  total: number;
  done: number;
  failed: number;
  status: string;
  started_at: string;
  finished_at: string | null;
}

export interface AnalysisQueueStatus {
  worker_alive: boolean;
  queued: number;
  pending_count: number;
  pending: PendingHat[];
  current_job: AnalysisJobRead | null;
  recent_jobs: AnalysisJobRead[];
}

/** Whether the scheduled-backup task is actually working. */
export interface BackupHealth {
  enabled: boolean;
  running: boolean;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
}

/** A set of hats that look like the same hat entered more than once. */
export interface DuplicateGroup {
  key: string;
  /** "exact" — every identity field agrees. "likely" — same model and size,
   *  with the colourway missing on at least one side (usually an unanalysed
   *  twin). Colourways that actively disagree are never grouped. */
  confidence: 'exact' | 'likely';
  label: string;
  hats: SearchResult[];
}
