export interface ShiftNote {
  id: string;
  author_id: string | null;
  shift_date: string;
  raw_text: string;
  polished_text: string | null;
  polish_error: string | null;
  model: string | null;
  created_at: string;
  updated_at: string;
}

export interface ShiftNoteList {
  items: ShiftNote[];
  shift_date: string;
}

export interface ShiftSummary {
  id: string;
  shift_date: string;
  generated_by: string | null;
  narrative: string;
  source_note_ids: string[];
  model: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export type ShiftExportFormat = "md" | "html";
