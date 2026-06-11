import { apiClient } from "./client";
import type { ShiftExportFormat, ShiftNote, ShiftNoteList, ShiftSummary } from "../types";

export async function listShiftNotes(shiftDate?: string): Promise<ShiftNoteList> {
  const { data } = await apiClient.get<ShiftNoteList>("/shift-log/notes", {
    params: shiftDate ? { shift_date: shiftDate } : undefined,
  });
  return data;
}

export async function createShiftNote(rawText: string, shiftDate?: string): Promise<ShiftNote> {
  const { data } = await apiClient.post<ShiftNote>("/shift-log/notes", {
    raw_text: rawText,
    shift_date: shiftDate,
  });
  return data;
}

export async function updateShiftNote(id: string, polishedText: string): Promise<ShiftNote> {
  const { data } = await apiClient.patch<ShiftNote>(`/shift-log/notes/${id}`, {
    polished_text: polishedText,
  });
  return data;
}

export async function repolishShiftNote(id: string): Promise<ShiftNote> {
  const { data } = await apiClient.post<ShiftNote>(`/shift-log/notes/${id}/repolish`);
  return data;
}

export async function deleteShiftNote(id: string): Promise<void> {
  await apiClient.delete(`/shift-log/notes/${id}`);
}

export async function getShiftSummary(shiftDate?: string): Promise<ShiftSummary | null> {
  const { data } = await apiClient.get<ShiftSummary | null>("/shift-log/summary", {
    params: shiftDate ? { shift_date: shiftDate } : undefined,
  });
  return data ?? null;
}

export async function generateShiftSummary(shiftDate?: string): Promise<ShiftSummary> {
  const { data } = await apiClient.post<ShiftSummary>("/shift-log/summary", undefined, {
    params: shiftDate ? { shift_date: shiftDate } : undefined,
  });
  return data;
}

export function shiftExportUrl(shiftDate: string, format: ShiftExportFormat): string {
  return `/api/v1/shift-log/export?shift_date=${encodeURIComponent(shiftDate)}&format=${format}`;
}
