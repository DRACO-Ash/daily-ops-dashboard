import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listNotifications } from "../api/notifications";
import SortableHeader from "../components/SortableHeader";
import type { Notification, NotificationSortColumn, SortDirection } from "../types";

const PAGE_SIZE = 50;

function formatDateTime(value: string | null): string {
  if (!value) return "n/a";
  return new Date(value).toISOString().replace("T", " ").slice(0, 19);
}

function formatSatIds(item: Notification): string {
  if (item.sat_ids && item.sat_ids.length > 0) {
    if (item.sat_ids.length <= 3) return item.sat_ids.join(", ");
    return `${item.sat_ids.slice(0, 3).join(", ")} (+${item.sat_ids.length - 3})`;
  }
  if (item.sat_no !== null && item.sat_no !== undefined) return String(item.sat_no);
  return "n/a";
}

function statusClass(status: string | null): string {
  if (!status) return "status-pill";
  return `status-pill status-${status.toLowerCase()}`;
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

export default function NotificationsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<Notification[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [eventTypeFilter, setEventTypeFilter] = useState<string | undefined>(undefined);
  const [eventTypeInput, setEventTypeInput] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [sortColumn, setSortColumn] = useState<NotificationSortColumn>("udl_created_at");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [reloadToken, setReloadToken] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const page = await listNotifications({
          event_type: eventTypeFilter,
          status: statusFilter,
          limit: PAGE_SIZE,
          offset,
          sort_by: sortColumn,
          sort_dir: sortDirection,
        });
        if (!cancelled) {
          setItems(page.items);
          setTotal(page.total);
        }
      } catch (err) {
        if (!cancelled) {
          setError(extractErrorMessage(err, "Failed to load notifications."));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [eventTypeFilter, statusFilter, offset, sortColumn, sortDirection, reloadToken]);

  function onSortChange(column: NotificationSortColumn) {
    if (column === sortColumn) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortColumn(column);
      setSortDirection("desc");
    }
    setOffset(0);
  }

  function onFilterSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = eventTypeInput.trim();
    setEventTypeFilter(trimmed === "" ? undefined : trimmed);
    setOffset(0);
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <h1>Notifications</h1>
      <p className="muted-paragraph">
        Auto-refreshing in the background; the dashboard always reflects the last 48 hours of
        TACREP_NOTSOs from UDL. The assistant analyses each new NOTSO against your uploaded
        procedures as it arrives.
      </p>

      <section className="card">
        <form onSubmit={onFilterSubmit} className="filter-form">
          <label>
            Event type (filter)
            <input
              type="text"
              value={eventTypeInput}
              onChange={(e) => setEventTypeInput(e.target.value)}
              placeholder="e.g. other, maneuver, launch"
            />
          </label>
          <label>
            Status
            <select
              value={statusFilter ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                setStatusFilter(v === "" ? undefined : v);
                setOffset(0);
              }}
            >
              <option value="">All</option>
              <option value="OPEN">OPEN</option>
              <option value="CLOSED">CLOSED</option>
            </select>
          </label>
          <button type="submit">Apply</button>
          <button
            type="button"
            onClick={() => {
              setEventTypeInput("");
              setEventTypeFilter(undefined);
              setStatusFilter(undefined);
              setOffset(0);
            }}
          >
            Clear
          </button>
          <button type="button" onClick={() => setReloadToken((t) => t + 1)}>
            Refresh
          </button>
        </form>

        {error && <div className="form-error">{error}</div>}
        {loading && <div>Loading...</div>}

        <table className="elsets-table">
          <thead>
            <tr>
              <SortableHeader
                column="notso_identifier"
                label="Notice"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <SortableHeader
                column="status"
                label="Status"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <SortableHeader
                column="event_type"
                label="Type"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <th>Event class</th>
              <th>Sat IDs</th>
              <SortableHeader
                column="udl_created_at"
                label="UDL created"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr
                key={it.id}
                className="clickable-row"
                onClick={() => navigate(`/notifications/${it.id}`)}
              >
                <td>{it.notso_identifier ?? it.notice_id ?? "n/a"}</td>
                <td>
                  {it.status ? <span className={statusClass(it.status)}>{it.status}</span> : "n/a"}
                </td>
                <td>{it.event_type ?? "n/a"}</td>
                <td className="event-class-cell">{it.event_class ?? "n/a"}</td>
                <td>{formatSatIds(it)}</td>
                <td>{formatDateTime(it.udl_created_at)}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6}>No notifications to show.</td>
              </tr>
            )}
          </tbody>
        </table>

        <div className="pagination">
          <span>
            {total} total &middot; page {currentPage} of {totalPages}
          </span>
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </button>
          <button
            type="button"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      </section>
    </div>
  );
}
