import type { AxiosResponse } from "axios";
import { apiClient } from "./client";
import type {
  Ask,
  AskCreate,
  AskResultPage,
  AskSuggestion,
  HistoryJob,
  HistoryJobCreate,
  MattermostChannel,
  MattermostListQuery,
  MattermostMessagePage,
  MattermostPerson,
} from "../types";

export async function listMattermostMessages(
  query: MattermostListQuery = {},
): Promise<MattermostMessagePage> {
  const { data } = await apiClient.get<MattermostMessagePage>("/mattermost/messages", {
    params: query,
  });
  return data;
}

/** Return the body only for a 2xx response; anything else is an error. */
function okData<T>(response: AxiosResponse<T>): T {
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`Unexpected response status ${response.status}`);
  }
  return response.data;
}

function askPath(id: string): string {
  return `/mattermost/asks/${encodeURIComponent(id)}`;
}

// Asks ------------------------------------------------------------------------

export async function listAsks(): Promise<Ask[]> {
  return okData(await apiClient.get<Ask[]>("/mattermost/asks"));
}

export async function getAsk(id: string): Promise<Ask> {
  return okData(await apiClient.get<Ask>(askPath(id)));
}

export async function createAsk(payload: AskCreate): Promise<Ask> {
  return okData(await apiClient.post<Ask>("/mattermost/asks", payload));
}

export async function updateAsk(id: string, payload: AskCreate): Promise<Ask> {
  return okData(await apiClient.put<Ask>(askPath(id), payload));
}

export async function deleteAsk(id: string): Promise<void> {
  const response = await apiClient.delete(askPath(id));
  if (response.status !== 204 && response.status !== 200) {
    throw new Error(`Unexpected response status ${response.status}`);
  }
}

/** Queue the ask; omit `runAt` to run on the next background cycle. */
export async function runAsk(id: string, runAt?: string): Promise<Ask> {
  const params = runAt ? { run_at: runAt } : undefined;
  return okData(await apiClient.post<Ask>(`${askPath(id)}/run`, null, { params }));
}

export async function unscheduleAsk(id: string): Promise<Ask> {
  return okData(await apiClient.post<Ask>(`${askPath(id)}/unschedule`));
}

export async function listAskResults(
  id: string,
  limit: number,
  offset: number,
): Promise<AskResultPage> {
  return okData(
    await apiClient.get<AskResultPage>(`${askPath(id)}/results`, { params: { limit, offset } }),
  );
}

export interface CsvDownload {
  blob: Blob;
  disposition: string | null;
}

/** Fetch the CSV through the client so the bearer token is sent. */
export async function downloadAskResultsCsv(id: string): Promise<CsvDownload> {
  const response = await apiClient.get<Blob>(`${askPath(id)}/results.csv`, {
    responseType: "blob",
  });
  const blob = okData(response);
  const header = response.headers["content-disposition"];
  return { blob, disposition: typeof header === "string" ? header : null };
}

export async function suggestAsk(question: string): Promise<AskSuggestion> {
  return okData(await apiClient.post<AskSuggestion>("/mattermost/asks/suggest", { question }));
}

export async function searchMattermostPeople(q: string): Promise<MattermostPerson[]> {
  return okData(await apiClient.get<MattermostPerson[]>("/mattermost/users", { params: { q } }));
}

export async function listMattermostChannels(): Promise<MattermostChannel[]> {
  return okData(await apiClient.get<MattermostChannel[]>("/mattermost/channels"));
}

// Full-history jobs -------------------------------------------------------------

export async function listHistoryJobs(): Promise<HistoryJob[]> {
  return okData(await apiClient.get<HistoryJob[]>("/mattermost/history-jobs"));
}

export async function createHistoryJob(payload: HistoryJobCreate): Promise<HistoryJob> {
  return okData(await apiClient.post<HistoryJob>("/mattermost/history-jobs", payload));
}

export async function cancelHistoryJob(id: string): Promise<HistoryJob> {
  return okData(
    await apiClient.post<HistoryJob>(`/mattermost/history-jobs/${encodeURIComponent(id)}/cancel`),
  );
}
