import { apiClient } from "./client";
import type {
  NotsoDetail,
  NotsoIngestRequest,
  NotsoIngestResponse,
  NotsoListQuery,
  NotsoPage,
} from "../types";

export async function listNotsos(query: NotsoListQuery = {}): Promise<NotsoPage> {
  const { data } = await apiClient.get<NotsoPage>("/notsos", { params: query });
  return data;
}

export async function getNotso(id: string): Promise<NotsoDetail> {
  const { data } = await apiClient.get<NotsoDetail>(`/notsos/${id}`);
  return data;
}

export async function triggerNotsoIngest(
  payload: NotsoIngestRequest,
): Promise<NotsoIngestResponse> {
  const { data } = await apiClient.post<NotsoIngestResponse>("/notsos/ingest", payload);
  return data;
}
