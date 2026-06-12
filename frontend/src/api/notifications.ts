import { apiClient } from "./client";
import type {
  NotificationDetail,
  NotificationIngestRequest,
  NotificationIngestResponse,
  NotificationListQuery,
  NotificationPage,
} from "../types";

export async function listNotifications(
  query: NotificationListQuery = {},
): Promise<NotificationPage> {
  const { data } = await apiClient.get<NotificationPage>("/notifications", {
    params: query,
  });
  return data;
}

export async function getNotification(id: string): Promise<NotificationDetail> {
  const { data } = await apiClient.get<NotificationDetail>(`/notifications/${id}`);
  return data;
}

export async function triggerNotificationIngest(
  payload: NotificationIngestRequest,
): Promise<NotificationIngestResponse> {
  const { data } = await apiClient.post<NotificationIngestResponse>(
    "/notifications/ingest",
    payload,
  );
  return data;
}

export async function refreshNotificationsNow(): Promise<void> {
  await apiClient.post("/notifications/refresh");
}
