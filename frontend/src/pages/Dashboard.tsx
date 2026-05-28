import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listElsets } from "../api/elsets";
import { listNotifications } from "../api/notifications";
import type { Elset, Notification } from "../types";

interface SurfaceStats {
  total: number;
  latest: { id: string; label: string; subtitle: string } | null;
}

function formatDateTime(value: string | null): string {
  if (!value) return "n/a";
  return new Date(value).toISOString().replace("T", " ").slice(0, 19);
}

function elsetToSurfaceStats(total: number, items: Elset[]): SurfaceStats {
  const latest = items[0];
  return {
    total,
    latest: latest
      ? {
          id: latest.id,
          label: `Sat ${latest.sat_no}`,
          subtitle: `Epoch ${formatDateTime(latest.epoch)}`,
        }
      : null,
  };
}

function notificationToSurfaceStats(total: number, items: Notification[]): SurfaceStats {
  const latest = items[0];
  return {
    total,
    latest: latest
      ? {
          id: latest.id,
          label: latest.notice_id ?? "Notification",
          subtitle: latest.msg_type
            ? `${latest.msg_type} · ${formatDateTime(latest.udl_created_at ?? latest.effective_from)}`
            : formatDateTime(latest.udl_created_at ?? latest.effective_from),
        }
      : null,
  };
}

export default function Dashboard() {
  const [elsets, setElsets] = useState<SurfaceStats | null>(null);
  const [notifications, setNotifications] = useState<SurfaceStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [elsetPage, notificationPage] = await Promise.all([
          listElsets({ limit: 1 }),
          listNotifications({ limit: 1 }),
        ]);
        if (!cancelled) {
          setElsets(elsetToSurfaceStats(elsetPage.total, elsetPage.items));
          setNotifications(
            notificationToSurfaceStats(notificationPage.total, notificationPage.items),
          );
        }
      } catch {
        if (!cancelled) setError("Failed to load dashboard.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1>Dashboard</h1>
      <p>Operational intelligence surfaces for space surveillance analysts.</p>

      {error && <div className="form-error">{error}</div>}
      {loading && <div>Loading...</div>}

      <div className="dashboard-grid">
        <Link to="/elsets" className="surface-card">
          <div className="surface-card-label">Element sets</div>
          <div className="surface-card-metric">{elsets?.total ?? 0}</div>
          {elsets?.latest && (
            <div className="surface-card-sub">
              Latest: {elsets.latest.label}
              <br />
              {elsets.latest.subtitle}
            </div>
          )}
        </Link>

        <Link to="/notifications" className="surface-card">
          <div className="surface-card-label">Notifications</div>
          <div className="surface-card-metric">{notifications?.total ?? 0}</div>
          {notifications?.latest && (
            <div className="surface-card-sub">
              Latest: {notifications.latest.label}
              <br />
              {notifications.latest.subtitle}
            </div>
          )}
        </Link>
      </div>
    </div>
  );
}
