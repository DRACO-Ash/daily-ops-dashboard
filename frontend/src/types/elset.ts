export interface Elset {
  id: string;
  udl_id: string | null;
  sat_no: number;
  epoch: string;
  mean_motion: number | null;
  eccentricity: number | null;
  inclination: number | null;
  raan: number | null;
  arg_of_perigee: number | null;
  mean_anomaly: number | null;
  rev_no: number | null;
  bstar: number | null;
  mean_motion_dot: number | null;
  mean_motion_ddot: number | null;
  semi_major_axis: number | null;
  period: number | null;
  apogee: number | null;
  perigee: number | null;
  line1: string | null;
  line2: string | null;
  classification_marking: string | null;
  data_mode: string | null;
  source: string | null;
  created_at: string;
  updated_at: string;
}

export interface ElsetDetail extends Elset {
  raw: Record<string, unknown>;
}

export interface ElsetPage {
  items: Elset[];
  total: number;
  limit: number;
  offset: number;
}

export interface ElsetIngestRequest {
  epoch_gte: string;
  sat_no?: number;
  max_results?: number;
}

export interface ElsetIngestResponse {
  pulled: number;
  inserted: number;
  updated: number;
  skipped: number;
}

export interface ElsetListQuery {
  sat_no?: number;
  epoch_gte?: string;
  epoch_lte?: string;
  limit?: number;
  offset?: number;
}
