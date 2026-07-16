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
  analysis_status: string | null;
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
