import { apiClient } from "./client";
import type { Procedure, ProcedureContent, ProcedurePage } from "../types";

export async function listProcedures(): Promise<ProcedurePage> {
  const { data } = await apiClient.get<ProcedurePage>("/procedures");
  return data;
}

export async function getProcedure(id: string): Promise<ProcedureContent> {
  const { data } = await apiClient.get<ProcedureContent>(`/procedures/${id}`);
  return data;
}

export async function uploadProcedure(
  name: string,
  description: string | null,
  file: File,
): Promise<Procedure> {
  const form = new FormData();
  form.append("name", name);
  if (description) form.append("description", description);
  form.append("file", file);
  const { data } = await apiClient.post<Procedure>("/procedures", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function deleteProcedure(id: string): Promise<void> {
  await apiClient.delete(`/procedures/${id}`);
}

export function procedureDownloadUrl(id: string): string {
  return `/api/v1/procedures/${id}/download`;
}
