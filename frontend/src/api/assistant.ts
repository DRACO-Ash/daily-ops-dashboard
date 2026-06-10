import { apiClient } from "./client";
import type { AssistantEvaluation } from "../types";

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
