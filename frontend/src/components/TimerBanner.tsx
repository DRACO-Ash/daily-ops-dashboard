import { useEventTimers } from "../context/EventTimersContext";

function formatTimeUtc(value: string): string {
  return new Date(value).toISOString().slice(11, 19) + "Z";
}

export default function TimerBanner() {
  const { firing, dismissTimer, audioEnabled, enableAudio, notificationPermission } =
    useEventTimers();

  if (firing.length === 0 && audioEnabled) return null;

  return (
    <div className="timer-banner-host">
      {!audioEnabled && (
        <div className="timer-banner timer-banner-info">
          <span>
            Audio alerts disabled. Click to enable sound and browser notifications for event timers.
          </span>
          <button type="button" onClick={() => void enableAudio()}>
            Enable alerts
          </button>
        </div>
      )}
      {firing.map((t) => (
        <div key={t.id} className="timer-banner timer-banner-firing">
          <div className="timer-banner-body">
            <strong>FIRING</strong>
            <span className="timer-banner-label">{t.label}</span>
            <span className="muted">target {formatTimeUtc(t.target_time)}</span>
            {t.event_key && <span className="muted">event {t.event_key}</span>}
            {notificationPermission === "denied" && (
              <span className="muted">Browser notifications denied; audio only.</span>
            )}
          </div>
          <button type="button" onClick={() => void dismissTimer(t.id)}>
            Dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
