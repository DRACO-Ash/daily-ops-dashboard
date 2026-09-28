import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getFeed } from "../api/assistant";
import type { AssistantFeedItem } from "../types";

const REFRESH_INTERVAL_MS = 60_000;

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "n/a";
  return new Date(value).toISOString().replace("T", " ").slice(0, 19);
}

function formatWindow(hours: number): string {
  if (hours > 0 && hours % 24 === 0) {
    const days = hours / 24;
    return days === 1 ? "1 day" : `${days} days`;
  }
  return hours === 1 ? "1 hour" : `${hours} hours`;
}

function urgencyClass(urgency: string): string {
  const lower = urgency.toLowerCase();
  if (lower === "high") return "urgency-pill urgency-high";
  if (lower === "medium") return "urgency-pill urgency-medium";
  if (lower === "low") return "urgency-pill urgency-low";
  if (lower === "pending") return "urgency-pill urgency-pending";
  return "urgency-pill";
}

function urgencyLabel(urgency: string): string {
  if (urgency === "pending") return "Awaiting analysis";
  if (urgency === "none") return "Informational";
  return urgency.charAt(0).toUpperCase() + urgency.slice(1);
}

function feedBucketsByUrgency(items: AssistantFeedItem[]): Map<string, AssistantFeedItem[]> {
  const order = ["high", "medium", "low", "none", "pending"];
  const map = new Map<string, AssistantFeedItem[]>();
  for (const k of order) map.set(k, []);
  for (const item of items) {
    const key = order.includes(item.urgency) ? item.urgency : "none";
    map.get(key)!.push(item);
  }
  return map;
}

function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "response" in err) {
    const response = (err as { response?: { data?: { detail?: unknown } } }).response;
    const detail = response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [items, setItems] = useState<AssistantFeedItem[]>([]);
  const [windowHours, setWindowHours] = useState(120);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null);

  const load = useCallback(async (signalLoading: boolean) => {
    if (signalLoading) setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const data = await getFeed();
      setItems(data.items);
      setWindowHours(data.window_hours);
      setLastLoadedAt(new Date());
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load the assistant feed."));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load(true);
  }, [load]);

  useEffect(() => {
    const id = globalThis.setInterval(() => {
      load(false);
    }, REFRESH_INTERVAL_MS);
    return () => globalThis.clearInterval(id);
  }, [load]);

  const buckets = feedBucketsByUrgency(items);
  const counts = {
    high: buckets.get("high")!.length,
    medium: buckets.get("medium")!.length,
    low: buckets.get("low")!.length,
    pending: buckets.get("pending")!.length,
    info: buckets.get("none")!.length,
  };

  if (loading) {
    return (
      <div>
        <h1>Dashboard</h1>
        <p>Loading assistant feed...</p>
      </div>
    );
  }

  return (
    <div>
      <div className="dashboard-header">
        <div>
          <h1>What needs your attention</h1>
          <p className="muted-paragraph">
            Last {formatWindow(windowHours)} of TACREP_NOTSOs, evaluated against your uploaded
            procedures. Most urgent first.
            {lastLoadedAt && (
              <>
                {" "}
                Last refreshed {formatDateTime(lastLoadedAt.toISOString())}
                {refreshing && " (refreshing...)"}
              </>
            )}
          </p>
        </div>
        <div>
          <button type="button" onClick={() => load(false)} disabled={refreshing}>
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {error && <div className="form-error">{error}</div>}

      <div className="dashboard-rollup">
        <div className="rollup-stat urgency-high">
          <span className="rollup-count">{counts.high}</span>
          <span className="rollup-label">High</span>
        </div>
        <div className="rollup-stat urgency-medium">
          <span className="rollup-count">{counts.medium}</span>
          <span className="rollup-label">Medium</span>
        </div>
        <div className="rollup-stat urgency-low">
          <span className="rollup-count">{counts.low}</span>
          <span className="rollup-label">Low</span>
        </div>
        <div className="rollup-stat urgency-pending">
          <span className="rollup-count">{counts.pending}</span>
          <span className="rollup-label">Pending</span>
        </div>
        <div className="rollup-stat">
          <span className="rollup-count">{counts.info}</span>
          <span className="rollup-label">Info only</span>
        </div>
      </div>

      {items.length === 0 ? (
        <section className="card">
          <p>
            No NOTSOs in the last {formatWindow(windowHours)}. When new ones arrive they'll appear
            here automatically.
          </p>
        </section>
      ) : (
        <section className="card">
          {(["high", "medium", "low", "pending", "none"] as const).map((bucket) => {
            const rows = buckets.get(bucket)!;
            if (rows.length === 0) return null;
            return (
              <div key={bucket} className="dashboard-bucket">
                <h2>
                  <span className={urgencyClass(bucket)}>{urgencyLabel(bucket)}</span>
                  <span className="bucket-count">{rows.length}</span>
                </h2>
                <ul className="action-feed">
                  {rows.map((it) => {
                    const n = it.notification;
                    const summary = it.evaluation?.summary;
                    return (
                      <li
                        key={n.id}
                        className="action-feed-item"
                        onClick={() => navigate(`/notifications/${n.id}`)}
                      >
                        <div className="action-feed-head">
                          <strong>{n.notso_identifier ?? n.notice_id ?? "Notification"}</strong>
                          <span className="muted">{formatDateTime(n.udl_created_at)}</span>
                        </div>
                        {n.event_class && <div className="action-feed-class">{n.event_class}</div>}
                        {it.event_summary && (
                          <p className="action-feed-evolution">
                            <span className="evolution-label">
                              Event evolution
                              {it.event_publication_count && it.event_publication_count > 1 && (
                                <> &middot; {it.event_publication_count} publications</>
                              )}
                            </span>
                            {it.event_summary}
                          </p>
                        )}
                        {summary && <p className="action-feed-summary">{summary}</p>}
                        {it.top_action && (
                          <div className="action-feed-action">
                            <strong>Next:</strong> {it.top_action}
                          </div>
                        )}
                        {bucket === "pending" && (
                          <div className="muted">Awaiting assistant analysis...</div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </section>
      )}
    </div>
  );
}
