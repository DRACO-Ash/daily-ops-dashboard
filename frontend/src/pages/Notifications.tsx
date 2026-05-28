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
  const [msgTypeFilter, setMsgTypeFilter] = useState<string | undefined>(undefined);
  const [msgTypeInput, setMsgTypeInput] = useState("");
  const [sortColumn, setSortColumn] = useState<NotificationSortColumn>("udl_created_at");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [reloadToken, setReloadToken] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [ingestCreatedAt, setIngestCreatedAt] = useState("");
  const [ingestMsgType, setIngestMsgType] = useState(DEFAULT_MSG_TYPE);
  const [ingestDataMode, setIngestDataMode] = useState("REAL");
  const [ingestSource, setIngestSource] = useState("");
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
          msg_type: msgTypeFilter,
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
  }, [msgTypeFilter, offset, sortColumn, sortDirection, reloadToken]);

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
    const trimmed = msgTypeInput.trim();
    setMsgTypeFilter(trimmed === "" ? undefined : trimmed);
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
              placeholder="e.g. TACREP_NOTSO"
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
            Source (optional)
            <input
              type="text"
              value={ingestSource}
              onChange={(e) => setIngestSource(e.target.value)}
              placeholder="e.g. JCO"
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
            Filter by message type
            <input
              type="text"
              value={msgTypeInput}
              onChange={(e) => setMsgTypeInput(e.target.value)}
              placeholder="e.g. TACREP_NOTSO"
            />
          </label>
          <button type="submit">Apply</button>
          <button
            type="button"
            onClick={() => {
              setMsgTypeInput("");
              setMsgTypeFilter(undefined);
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
                column="notice_id"
                label="Notice"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <SortableHeader
                column="msg_type"
                label="Type"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <SortableHeader
                column="udl_created_at"
                label="UDL created"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <SortableHeader
                column="effective_from"
                label="Effective from"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <SortableHeader
                column="sat_no"
                label="Sat No"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <th>Subject</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr
                key={it.id}
                className="clickable-row"
                onClick={() => navigate(`/notifications/${it.id}`)}
              >
                <td>{it.notice_id ?? "n/a"}</td>
                <td>{it.msg_type ?? "n/a"}</td>
                <td>{formatDateTime(it.udl_created_at)}</td>
                <td>{formatDateTime(it.effective_from)}</td>
                <td>{it.sat_no ?? "n/a"}</td>
                <td>{it.subject ?? "n/a"}</td>
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
