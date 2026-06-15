import { apiClient } from "./client";
import type { AssistantEvaluation, AssistantFeed } from "../types";

export async function getFeed(hours?: number, limit = 100): Promise<AssistantFeed> {
  // Omitting `hours` lets the backend fall back to its configured
  // notification window (5 days by default) so the dashboard stays
  // in sync with the ingest pipeline without the client guessing.
  const params: Record<string, number> = { limit };
  if (hours !== undefined) params.hours = hours;
  const { data } = await apiClient.get<AssistantFeed>("/assistant/feed", { params });
  return data;
}

export async function getEvaluation(notificationId: string): Promise<AssistantEvaluation | null> {
  try {
    const { data } = await apiClient.get<AssistantEvaluation>(
      `/assistant/evaluation/${notificationId}`,
    );
    return data;
  } catch (err) {
    if (err && typeof err === "object" && "response" in err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 404) return null;
    }
    throw err;
  }
}

export async function runEvaluation(notificationId: string): Promise<AssistantEvaluation> {
  const { data } = await apiClient.post<AssistantEvaluation>(
    `/assistant/evaluate/${notificationId}`,
  );
  return data;
}
