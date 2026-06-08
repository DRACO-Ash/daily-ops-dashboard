export interface Notification {
  id: string;
  udl_id: string | null;

  msg_type: string | null;
  data_mode: string | null;
  source: string | null;
  classification_marking: string | null;
  created_by: string | null;
  orig_network: string | null;
  udl_created_at: string | null;

  notso_identifier: string | null;
  notice_id: string | null;
  event_id: string | null;

  event_class: string | null;
  event_type: string | null;
  status: string | null;

  subject: string | null;
  description: string | null;
  region: string | null;
  notso_link: string | null;
  company_name: string | null;

  publish_date: string | null;
  effective_from: string | null;
  effective_until: string | null;

  sat_no: number | null;
  sat_ids: string[] | null;

  created_at: string;
  updated_at: string;
}

export interface NotificationDetail extends Notification {
  raw: Record<string, unknown>;
}

export interface NotificationPage {
  items: Notification[];
  total: number;
  limit: number;
  offset: number;
}

export interface NotificationIngestRequest {
  msg_type?: string;
  created_at_gte?: string;
  data_mode?: string;
  source?: string;
  max_results?: number;
}

export interface NotificationIngestResponse {
  pulled: number;
  inserted: number;
  updated: number;
  skipped: number;
}

export type NotificationSortColumn =
  | "notso_identifier"
  | "notice_id"
  | "msg_type"
  | "event_type"
  | "status"
  | "publish_date"
  | "effective_from"
  | "effective_until"
  | "sat_no"
  | "udl_created_at"
  | "created_at";

export interface NotificationListQuery {
  msg_type?: string;
  event_type?: string;
  status?: string;
  sat_no?: number;
  effective_from_gte?: string;
  effective_from_lte?: string;
  created_at_gte?: string;
  limit?: number;
  offset?: number;
  sort_by?: NotificationSortColumn;
  sort_dir?: "asc" | "desc";
}
