import {
  ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  acknowledgePreAlert as apiAck,
  createEventTimer as apiCreate,
  deleteEventTimer as apiDelete,
  dismissEventTimer as apiDismiss,
  listEventTimers,
} from "../api/event_timers";
import { playFiring, playPreAlert, unlockAudio } from "../utils/timerSound";
import type { EventTimer, EventTimerCreate } from "../types";

const POLL_INTERVAL_MS = 10_000;
const RECURRING_BEEP_INTERVAL_MS = 30_000;

interface EventTimersContextValue {
  timers: EventTimer[];
  firing: EventTimer[];
  preAlerting: EventTimer[];
  upcoming: EventTimer[];
  dismissed: EventTimer[];
  loading: boolean;
  error: string | null;
  audioEnabled: boolean;
  notificationPermission: NotificationPermission | "unsupported";
  enableAudio: () => Promise<void>;
  refresh: () => Promise<void>;
  createTimer: (payload: EventTimerCreate) => Promise<EventTimer>;
  acknowledgePreAlert: (id: string) => Promise<void>;
  dismissTimer: (id: string) => Promise<void>;
  deleteTimer: (id: string) => Promise<void>;
}

const Ctx = createContext<EventTimersContextValue | null>(null);

function classify(timers: EventTimer[]) {
  const now = Date.now();
  const firing: EventTimer[] = [];
  const preAlerting: EventTimer[] = [];
  const upcoming: EventTimer[] = [];
  const dismissed: EventTimer[] = [];
  for (const t of timers) {
    const target = new Date(t.target_time).getTime();
    const preStart = target - t.pre_alert_minutes * 60 * 1000;
    if (t.dismissed_at) {
      dismissed.push(t);
      continue;
    }
    if (now >= target) {
      firing.push(t);
    } else if (now >= preStart) {
      preAlerting.push(t);
    } else {
      upcoming.push(t);
    }
  }
  return { firing, preAlerting, upcoming, dismissed };
}

export function EventTimersProvider({ children }: { children: ReactNode }) {
  const [timers, setTimers] = useState<EventTimer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [notificationPermission, setNotificationPermission] = useState<
    NotificationPermission | "unsupported"
  >(typeof Notification === "undefined" ? "unsupported" : Notification.permission);

  // Track which timers we have already played the pre-alert beep for
  // in this browser session, independent of the server-side
  // pre_alert_fired_at flag — that flag persists across sessions, but
  // we still want a chime on the first poll after page load if the
  // operator hasn't acked yet.
  const alertedPreAlertIdsRef = useRef<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const data = await listEventTimers(false);
      setTimers(data.items);
      setError(null);
    } catch (err) {
      const message =
        err && typeof err === "object" && "response" in err
          ? "Could not load timers."
          : err instanceof Error
            ? err.message
            : "Could not load timers.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = globalThis.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => globalThis.clearInterval(id);
  }, [refresh]);

  // First user gesture anywhere unlocks the AudioContext. We also keep
  // a passive "Enable sound" button visible until then in case the
  // operator never clicks for a long stretch.
  useEffect(() => {
    function onFirstInteraction() {
      unlockAudio();
      setAudioEnabled(true);
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        Notification.requestPermission()
          .then((perm) => setNotificationPermission(perm))
          .catch(() => undefined);
      }
    }
    globalThis.addEventListener("click", onFirstInteraction, { once: true });
    globalThis.addEventListener("keydown", onFirstInteraction, { once: true });
    return () => {
      globalThis.removeEventListener("click", onFirstInteraction);
      globalThis.removeEventListener("keydown", onFirstInteraction);
    };
  }, []);

  const enableAudio = useCallback(async () => {
    unlockAudio();
    setAudioEnabled(true);
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      try {
        const perm = await Notification.requestPermission();
        setNotificationPermission(perm);
      } catch {
        /* swallow */
      }
    }
  }, []);

  const { firing, preAlerting, upcoming, dismissed } = useMemo(() => classify(timers), [timers]);

  // Pre-alert: fire ONCE per timer per session when it enters the
  // pre-alert window. Server stamp `pre_alert_fired_at` records the
  // operator's first acknowledgement; the per-session set prevents
  // double-firing on subsequent polls within the same load.
  useEffect(() => {
    for (const t of preAlerting) {
      if (t.pre_alert_fired_at) continue;
      if (alertedPreAlertIdsRef.current.has(t.id)) continue;
      alertedPreAlertIdsRef.current.add(t.id);
      playPreAlert();
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        new Notification("Event in 5 minutes", {
          body: t.label,
          tag: `event-timer-pre-${t.id}`,
        });
      }
      apiAck(t.id).catch(() => undefined);
    }
  }, [preAlerting]);

  // Recurring beep for firing timers. One global interval so we don't
  // multiply timers as new ones light up.
  const firingRef = useRef<EventTimer[]>(firing);
  firingRef.current = firing;
  useEffect(() => {
    if (firing.length === 0) return;
    const id = globalThis.setInterval(() => {
      const current = firingRef.current;
      if (current.length === 0) return;
      playFiring();
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        for (const t of current) {
          new Notification("Event firing", {
            body: t.label,
            tag: `event-timer-firing-${t.id}`,
            requireInteraction: true,
          });
        }
      }
    }, RECURRING_BEEP_INTERVAL_MS);
    return () => globalThis.clearInterval(id);
  }, [firing.length]);

  // Also play once the moment a timer first transitions into firing,
  // so the operator gets immediate feedback rather than waiting up to
  // 30 seconds for the recurring tick.
  const previouslyFiringRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const previous = previouslyFiringRef.current;
    const current = new Set(firing.map((t) => t.id));
    for (const t of firing) {
      if (!previous.has(t.id)) {
        playFiring();
        if (typeof Notification !== "undefined" && Notification.permission === "granted") {
          new Notification("Event firing", {
            body: t.label,
            tag: `event-timer-firing-${t.id}`,
            requireInteraction: true,
          });
        }
      }
    }
    previouslyFiringRef.current = current;
  }, [firing]);

  const createTimer = useCallback(async (payload: EventTimerCreate) => {
    const created = await apiCreate(payload);
    setTimers((prev) => [...prev, created]);
    return created;
  }, []);

  const acknowledgePreAlertById = useCallback(async (id: string) => {
    const updated = await apiAck(id);
    setTimers((prev) => prev.map((t) => (t.id === id ? updated : t)));
  }, []);

  const dismissTimerById = useCallback(async (id: string) => {
    const updated = await apiDismiss(id);
    setTimers((prev) => prev.map((t) => (t.id === id ? updated : t)));
  }, []);

  const deleteTimerById = useCallback(async (id: string) => {
    await apiDelete(id);
    setTimers((prev) => prev.filter((t) => t.id !== id));
    alertedPreAlertIdsRef.current.delete(id);
  }, []);

  const value: EventTimersContextValue = {
    timers,
    firing,
    preAlerting,
    upcoming,
    dismissed,
    loading,
    error,
    audioEnabled,
    notificationPermission,
    enableAudio,
    refresh,
    createTimer,
    acknowledgePreAlert: acknowledgePreAlertById,
    dismissTimer: dismissTimerById,
    deleteTimer: deleteTimerById,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useEventTimers(): EventTimersContextValue {
  const v = useContext(Ctx);
  if (v === null) {
    throw new Error("useEventTimers must be used inside EventTimersProvider");
  }
  return v;
}
