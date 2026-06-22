export type TimerRecurrence = "none" | "daily" | "weekly" | "monthly";

export interface EventTimer {
  id: string;
  event_key: string | null;
  label: string;
  target_time: string;
  pre_alert_minutes: number;
  recurrence: TimerRecurrence | string;
  pre_alert_fired_at: string | null;
  dismissed_at: string | null;
  dismissed_by: string | null;
  created_by: string | null;
  shift_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface EventTimerList {
  items: EventTimer[];
}

export interface EventTimerCreate {
  label: string;
  target_time: string;
  event_key?: string | null;
  pre_alert_minutes?: number;
  recurrence?: TimerRecurrence;
  shift_date?: string | null;
}
