import { apiClient } from "./client";
import type { MattermostListQuery, MattermostMessagePage } from "../types";

export async function listMattermostMessages(
  query: MattermostListQuery = {},
): Promise<MattermostMessagePage> {
  const { data } = await apiClient.get<MattermostMessagePage>("/mattermost/messages", {
    params: query,
  });
  return data;
}
