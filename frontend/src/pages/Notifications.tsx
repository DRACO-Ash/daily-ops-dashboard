import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listNotifications, triggerNotificationIngest } from "../api/notifications";
import SortableHeader from "../components/SortableHeader";
import type {
  Notification,
  NotificationIngestResponse,
  NotificationSortColumn,
  SortDirection,
} from "../types";

const PAGE_SIZE = 50;
const DEFAULT_MSG_TYPE = "TACREP_NOTSO";

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

  const [ingestCreatedAt, setIngestCreatedAt] = useState("");
  const [ingestMsgType, setIngestMsgType] = useState(DEFAULT_MSG_TYPE);
  const [ingestDataMode, setIngestDataMode] = useState("REAL");
  const [ingestSource, setIngestSource] = useState("JCO");
  const [ingestMaxResults, setIngestMaxResults] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState<NotificationIngestResponse | null>(null);

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

  async function onIngestSubmit(event: FormEvent) {
    event.preventDefault();
    setIngesting(true);
    setIngestResult(null);
    setError(null);
    try {
      const result = await triggerNotificationIngest({
        msg_type: ingestMsgType.trim() || undefined,
        created_at_gte: ingestCreatedAt ? new Date(ingestCreatedAt).toISOString() : undefined,
        data_mode: ingestDataMode.trim() || undefined,
        source: ingestSource.trim() || undefined,
        max_results: ingestMaxResults ? Number(ingestMaxResults) : undefined,
      });
      setIngestResult(result);
      setOffset(0);
      setReloadToken((t) => t + 1);
    } catch (err) {
      setError(extractErrorMessage(err, "Ingest failed."));
    } finally {
      setIngesting(false);
    }
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <h1>Notifications</h1>
      <p className="muted-paragraph">
        UDL serves Tactical Reports (TACREP) and Notices to Space Operators (NOTSO) through a single
        notification endpoint under <code>msgType=TACREP_NOTSO</code>. Other UDL notification types
        land here too.
      </p>

      <section className="card">
        <h2>Trigger UDL ingest</h2>
        <form onSubmit={onIngestSubmit} className="ingest-form">
          <label>
            Message type
            <input
              type="text"
              value={ingestMsgType}
              onChange={(e) => setIngestMsgType(e.target.value)}
              placeholder="TACREP_NOTSO"
            />
          </label>
          <label>
            Created since (optional)
            <input
              type="datetime-local"
              value={ingestCreatedAt}
              onChange={(e) => setIngestCreatedAt(e.target.value)}
            />
          </label>
          <label>
            Data mode
            <input
              type="text"
              value={ingestDataMode}
              onChange={(e) => setIngestDataMode(e.target.value)}
              placeholder="REAL"
            />
          </label>
          <label>
            Source
            <input
              type="text"
              value={ingestSource}
              onChange={(e) => setIngestSource(e.target.value)}
              placeholder="JCO"
            />
          </label>
          <label>
            Max results (optional)
            <input
              type="number"
              value={ingestMaxResults}
              onChange={(e) => setIngestMaxResults(e.target.value)}
              placeholder="e.g. 100"
            />
          </label>
          <button type="submit" disabled={ingesting}>
            {ingesting ? "Pulling..." : "Pull from UDL"}
          </button>
        </form>
        {ingestResult && (
          <div className="ingest-result">
            Pulled {ingestResult.pulled} &middot; Inserted {ingestResult.inserted} &middot; Updated{" "}
            {ingestResult.updated} &middot; Skipped {ingestResult.skipped}
          </div>
        )}
      </section>

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
