import { apiClient } from "./client";
import type { ManeuverDetail, ManeuverListQuery, ManeuverPage } from "../types";

export async function listManeuvers(query: ManeuverListQuery = {}): Promise<ManeuverPage> {
  const { data } = await apiClient.get<ManeuverPage>("/maneuvers", { params: query });
  return data;
}

export async function getManeuver(id: string): Promise<ManeuverDetail> {
  const { data } = await apiClient.get<ManeuverDetail>(`/maneuvers/${id}`);
  return data;
}
