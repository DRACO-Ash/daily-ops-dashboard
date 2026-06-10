export interface Maneuver {
  id: string;
  udl_id: string | null;
  data_mode: string | null;
  source: string | null;
  classification_marking: string | null;
  created_by: string | null;
  orig_network: string | null;
  origin: string | null;
  udl_created_at: string | null;
  sat_no: number | null;
  event_start_time: string | null;
  event_stop_time: string | null;
  mnvr_type: string | null;
  description: string | null;
  delta_v: number | null;
  thrust_magnitude: number | null;
  thrust_duration: number | null;
  propulsion_type: string | null;
  maneuver_status: string | null;
  responsible_nation: string | null;
  created_at: string;
  updated_at: string;
}

export interface ManeuverDetail extends Maneuver {
  raw: Record<string, unknown>;
}

export interface ManeuverPage {
  items: Maneuver[];
  total: number;
  limit: number;
  offset: number;
}

export type ManeuverSortColumn =
  | "sat_no"
  | "event_start_time"
  | "event_stop_time"
  | "mnvr_type"
  | "udl_created_at"
  | "created_at";

export interface ManeuverListQuery {
  sat_no?: number;
  mnvr_type?: string;
  event_start_time_gte?: string;
  event_start_time_lte?: string;
  limit?: number;
  offset?: number;
  sort_by?: ManeuverSortColumn;
  sort_dir?: "asc" | "desc";
}
