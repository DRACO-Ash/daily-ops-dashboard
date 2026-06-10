export interface Procedure {
  id: string;
  name: string;
  description: string | null;
  filename: string;
  content_type: string;
  size_bytes: number;
  file_hash: string;
  uploaded_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProcedureContent extends Procedure {
  content: string | null;
  content_truncated: boolean;
}

export interface ProcedurePage {
  items: Procedure[];
  total: number;
}
