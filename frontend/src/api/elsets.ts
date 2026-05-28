import { apiClient } from "./client";
import type {
  ElsetDetail,
  ElsetIngestRequest,
  ElsetIngestResponse,
  ElsetListQuery,
  ElsetPage,
} from "../types";

export async function listElsets(query: ElsetListQuery = {}): Promise<ElsetPage> {
  const { data } = await apiClient.get<ElsetPage>("/elsets", { params: query });
  return data;
}

export async function getElset(id: string): Promise<ElsetDetail> {
  const { data } = await apiClient.get<ElsetDetail>(`/elsets/${id}`);
  return data;
}

export async function triggerElsetIngest(
  payload: ElsetIngestRequest,
): Promise<ElsetIngestResponse> {
  const { data } = await apiClient.post<ElsetIngestResponse>("/elsets/ingest", payload);
  return data;
}
