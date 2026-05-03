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
  size: string;
  style: string;
  is_beanie: boolean;
  colors: ColorTag[];
  room_id: number | null;
  room_name: string | null;

  // AI / pricing
  brand: string | null;
  model_name: string | null;
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

  created_at: string;
  updated_at: string;
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
  colors: ColorTag[];
  room_id: number | null;
  room_name: string | null;
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
