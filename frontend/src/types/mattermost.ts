export interface MattermostMessage {
  id: string;
  mm_post_id: string;
  channel_id: string;
  channel_name: string | null;
  user_id: string;
  user_display_name: string | null;
  posted_at: string;
  message: string;
  post_type: string | null;
  root_id: string | null;
  edited_at: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MattermostMessagePage {
  items: MattermostMessage[];
  total: number;
  limit: number;
  offset: number;
}

export interface MattermostListQuery {
  channel_id?: string;
  user_id?: string;
  posted_at_gte?: string;
  include_deleted?: boolean;
  limit?: number;
  offset?: number;
}
