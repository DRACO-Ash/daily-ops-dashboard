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

// Asks ------------------------------------------------------------------------

export type AskScope = "posts" | "thread_starts" | "first_per_thread";
export type AskExtractSource = "message" | "thread_title";
export type AskStatus = "ok" | "partial" | "failed" | "queued";

export interface AskExtract {
  pattern: string;
  source: AskExtractSource;
}

export interface AskSpec {
  terms: string[];
  any_terms: string[];
  authors: string[];
  channels: string[];
  after: string | null;
  before: string | null;
  include_archived: boolean;
  scope: AskScope;
  extract: AskExtract | null;
}

export interface AskCreate {
  name: string;
  question: string | null;
  spec: AskSpec;
  refresh_minutes: number | null;
}

export interface Ask {
  id: string;
  name: string;
  question: string | null;
  spec: AskSpec;
  refresh_minutes: number | null;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: AskStatus | null;
  last_error: string | null;
  result_count: number;
  created_at: string;
  updated_at: string;
}

export interface AskResult {
  mm_post_id: string;
  channel_id: string;
  channel_name: string | null;
  channel_archived: boolean;
  thread_id: string;
  thread_title: string | null;
  thread_started_at: string | null;
  author: string | null;
  posted_at: string;
  extracted: string | null;
  excerpt: string;
  permalink: string | null;
}

export interface AskResultPage {
  items: AskResult[];
  total: number;
  limit: number;
  offset: number;
}

export interface AskSuggestion {
  name: string;
  spec: AskSpec;
  explanation: string;
}

export interface MattermostPerson {
  username: string | null;
  name: string | null;
  nickname: string | null;
}

export interface MattermostChannel {
  id: string;
  name: string;
  display_name: string | null;
  type: "O" | "P";
  archived: boolean;
  history_complete: boolean;
}

// Full-history jobs -------------------------------------------------------------

export type HistoryJobStatus = "scheduled" | "running" | "done" | "failed" | "cancelled";

export interface HistoryJob {
  id: string;
  channel_ids: string[];
  run_after: string;
  status: HistoryJobStatus;
  started_at: string | null;
  finished_at: string | null;
  counts: Record<string, number>;
  failed_channel_ids: string[];
  error: string | null;
  created_at: string;
}

export interface HistoryJobCreate {
  channel_ids: string[];
  run_after: string | null;
}
