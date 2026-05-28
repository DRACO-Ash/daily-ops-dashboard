export interface AuditLog {
  id: string;
  timestamp: string;
  user_id: string | null;
  action_type: string;
  entity_type: string | null;
  entity_id: string | null;
  ip_address: string | null;
  detail: string | null;
  previous_hash: string | null;
  entry_hash: string;
}

export interface AuditLogPage {
  items: AuditLog[];
  total: number;
  limit: number;
  offset: number;
}

export interface AuditLogQuery {
  action_type?: string;
  user_id?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}
