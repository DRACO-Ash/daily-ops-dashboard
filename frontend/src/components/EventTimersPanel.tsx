import { FormEvent, useState } from "react";
import { useEventTimers } from "../context/EventTimersContext";
import type { EventTimer } from "../types";

function toIsoUtc(local: string): string {
  // datetime-local fields hand back values in the operator's local zone
  // with no offset. The backend expects UTC ISO, so convert.
  if (!local) return "";
  const d = new Date(local);
  return d.toISOString();
}

function formatTime(value: string): string {
  return new Date(value).toISOString().replace("T", " ").slice(0, 19) + "Z";
}

function formatDelta(target: string): string {
  const diff = new Date(target).getTime() - Date.now();
  if (diff <= 0) return "now";
  const totalSec = Math.floor(diff / 1000);
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const mins = Math.floor((totalSec % 3600) / 60);
  if (days > 0) return `in ${days}d ${hours}h`;
  if (hours > 0) return `in ${hours}h ${mins}m`;
  return `in ${mins}m`;
}

interface TimerRowProps {
  timer: EventTimer;
  variant: "upcoming" | "firing" | "pre" | "dismissed";
}

function TimerRow({ timer, variant }: TimerRowProps) {
  const { dismissTimer, deleteTimer } = useEventTimers();
  const [busy, setBusy] = useState(false);

  async function onDismiss() {
    setBusy(true);
    try {
      await dismissTimer(timer.id);
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!window.confirm("Delete this timer?")) return;
    setBusy(true);
    try {
      await deleteTimer(timer.id);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={`event-timer-row event-timer-${variant}`}>
      <div className="event-timer-head">
        <strong>{timer.label}</strong>
        <span className="muted">{formatTime(timer.target_time)}</span>
      </div>
      <div className="event-timer-meta">
        {variant === "upcoming" && <span>{formatDelta(timer.target_time)}</span>}
        {variant === "pre" && <span className="urgency-pill urgency-medium">5-min alert</span>}
        {variant === "firing" && <span className="urgency-pill urgency-high">Firing</span>}
        {variant === "dismissed" && <span className="muted">Dismissed</span>}
        {timer.event_key && <span className="muted">event {timer.event_key}</span>}
      </div>
      <div className="event-timer-actions">
        {(variant === "firing" || variant === "pre") && (
          <button type="button" onClick={onDismiss} disabled={busy}>
            Dismiss
          </button>
        )}
        <button type="button" onClick={onDelete} disabled={busy}>
          Delete
        </button>
      </div>
    </li>
  );
}

export default function EventTimersPanel() {
  const { firing, preAlerting, upcoming, dismissed, error, createTimer } = useEventTimers();
  const [label, setLabel] = useState("");
  const [eventKey, setEventKey] = useState("");
  const [targetTime, setTargetTime] = useState("");
  const [preMinutes, setPreMinutes] = useState("5");
  const [submitting, setSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!label.trim() || !targetTime) return;
    setSubmitting(true);
    setCreateError(null);
    try {
      await createTimer({
        label: label.trim(),
        target_time: toIsoUtc(targetTime),
        event_key: eventKey.trim() || null,
        pre_alert_minutes: Math.max(0, Number(preMinutes) || 0),
      });
      setLabel("");
      setEventKey("");
      setTargetTime("");
      setPreMinutes("5");
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Could not create timer.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="card event-timers-card">
      <div className="event-timers-head">
        <h2>Event timers</h2>
        <span className="muted">
          {firing.length} firing &middot; {preAlerting.length} pre-alert &middot; {upcoming.length}{" "}
          upcoming
        </span>
      </div>

      <form onSubmit={onSubmit} className="filter-form event-timer-form">
        <label>
          Label
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. ISS station-keeping burn"
            required
          />
        </label>
        <label>
          Event ID (optional)
          <input
            type="text"
            value={eventKey}
            onChange={(e) => setEventKey(e.target.value)}
            placeholder="event_id or NOTSO number"
          />
        </label>
        <label>
          Target time (local)
          <input
            type="datetime-local"
            value={targetTime}
            onChange={(e) => setTargetTime(e.target.value)}
            required
          />
        </label>
        <label>
          Pre-alert (min)
          <input
            type="number"
            value={preMinutes}
            min="0"
            max="720"
            onChange={(e) => setPreMinutes(e.target.value)}
          />
        </label>
        <button type="submit" disabled={submitting || !label.trim() || !targetTime}>
          {submitting ? "Adding..." : "Add timer"}
        </button>
      </form>

      {(error || createError) && <div className="form-error">{createError ?? error}</div>}

      {firing.length === 0 &&
        preAlerting.length === 0 &&
        upcoming.length === 0 &&
        dismissed.length === 0 && <p className="muted">No timers set.</p>}

      <ul className="event-timers-list">
        {firing.map((t) => (
          <TimerRow key={t.id} timer={t} variant="firing" />
        ))}
        {preAlerting.map((t) => (
          <TimerRow key={t.id} timer={t} variant="pre" />
        ))}
        {upcoming.map((t) => (
          <TimerRow key={t.id} timer={t} variant="upcoming" />
        ))}
        {dismissed.map((t) => (
          <TimerRow key={t.id} timer={t} variant="dismissed" />
        ))}
      </ul>
    </section>
  );
}
