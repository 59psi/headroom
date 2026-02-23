export interface ColorTag {
  color_name: string;
  general_color: string;
  hex_value: string;
  dominance_rank: number;
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
