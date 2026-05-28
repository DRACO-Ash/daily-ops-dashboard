export interface Notso {
  id: string;
  udl_id: string | null;
  notice_id: string | null;
  msg_type: string | null;
  effective_from: string | null;
  effective_until: string | null;
  subject: string | null;
  description: string | null;
  sat_no: number | null;
  region: string | null;
  classification_marking: string | null;
  data_mode: string | null;
  source: string | null;
  udl_created_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotsoDetail extends Notso {
  raw: Record<string, unknown>;
}

export interface NotsoPage {
  items: Notso[];
  total: number;
  limit: number;
  offset: number;
}

export interface NotsoIngestRequest {
  effective_from_gte?: string;
  msg_type?: string;
  max_results?: number;
}

export interface NotsoIngestResponse {
  pulled: number;
  inserted: number;
  updated: number;
  skipped: number;
}

export type NotsoSortColumn =
  | "notice_id"
  | "msg_type"
  | "effective_from"
  | "effective_until"
  | "sat_no"
  | "created_at";

export interface NotsoListQuery {
  msg_type?: string;
  sat_no?: number;
  effective_from_gte?: string;
  effective_from_lte?: string;
  limit?: number;
  offset?: number;
  sort_by?: NotsoSortColumn;
  sort_dir?: "asc" | "desc";
}
