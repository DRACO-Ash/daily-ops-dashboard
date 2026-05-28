import { apiClient } from "./client";
import type { AuditLogPage, AuditLogQuery } from "../types";

export async function listAuditLog(query: AuditLogQuery = {}): Promise<AuditLogPage> {
  const { data } = await apiClient.get<AuditLogPage>("/audit", { params: query });
  return data;
}
