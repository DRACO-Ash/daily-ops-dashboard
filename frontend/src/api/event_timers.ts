import { apiClient } from "./client";
import type { EventTimer, EventTimerCreate, EventTimerList } from "../types";

export async function listEventTimers(includeDismissed = false): Promise<EventTimerList> {
  const { data } = await apiClient.get<EventTimerList>("/event-timers", {
    params: { include_dismissed: includeDismissed },
  });
  return data;
}

export async function createEventTimer(payload: EventTimerCreate): Promise<EventTimer> {
  const { data } = await apiClient.post<EventTimer>("/event-timers", payload);
  return data;
}

export async function acknowledgePreAlert(id: string): Promise<EventTimer> {
  const { data } = await apiClient.post<EventTimer>(`/event-timers/${id}/acknowledge-pre-alert`);
  return data;
}

export async function dismissEventTimer(id: string): Promise<EventTimer> {
  const { data } = await apiClient.post<EventTimer>(`/event-timers/${id}/dismiss`);
  return data;
}

export async function deleteEventTimer(id: string): Promise<void> {
  await apiClient.delete(`/event-timers/${id}`);
}
