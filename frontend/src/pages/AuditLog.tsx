import { FormEvent, useEffect, useState } from "react";
import { listAuditLog } from "../api/audit";
import type { AuditLog } from "../types";

const PAGE_SIZE = 50;

function formatTimestamp(value: string): string {
  return new Date(value).toISOString().replace("T", " ").slice(0, 19);
}

function shorten(id: string | null, n = 8): string {
  if (!id) return "n/a";
  return id.length > n ? `${id.slice(0, n)}…` : id;
}

function formatDetail(detail: string | null): string {
  if (!detail) return "";
  try {
    return JSON.stringify(JSON.parse(detail));
  } catch {
    return detail;
  }
}

function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === "object" && "response" in err) {
    const response = (
      err as {
        response?: { data?: { detail?: unknown }; status?: number };
      }
    ).response;
    if (response?.status === 403) {
      return "Insufficient privileges. Operator or admin role required.";
    }
    const detail = response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function AuditLogPage() {
  const [items, setItems] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [actionTypeFilter, setActionTypeFilter] = useState<string | undefined>(undefined);
  const [actionTypeInput, setActionTypeInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const page = await listAuditLog({
          action_type: actionTypeFilter,
          limit: PAGE_SIZE,
          offset,
        });
        if (!cancelled) {
          setItems(page.items);
          setTotal(page.total);
        }
      } catch (err) {
        if (!cancelled) {
          setError(extractErrorMessage(err, "Failed to load audit log."));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [actionTypeFilter, offset]);

  function onFilterSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = actionTypeInput.trim();
    setActionTypeFilter(trimmed === "" ? undefined : trimmed);
    setOffset(0);
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <h1>Audit log</h1>
      <p className="muted-paragraph">
        Append-only, tamper-evident record of every state-changing action. Visible to operators and
        administrators only.
      </p>

      <section className="card">
        <form onSubmit={onFilterSubmit} className="filter-form">
          <label>
            Filter by action type
            <input
              type="text"
              value={actionTypeInput}
              onChange={(e) => setActionTypeInput(e.target.value)}
              placeholder="e.g. udl.elset.ingest"
            />
          </label>
          <button type="submit">Apply</button>
          <button
            type="button"
            onClick={() => {
              setActionTypeInput("");
              setActionTypeFilter(undefined);
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
              <th>Timestamp</th>
              <th>Action</th>
              <th>Entity</th>
              <th>User</th>
              <th>IP</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id}>
                <td>{formatTimestamp(it.timestamp)}</td>
                <td>{it.action_type}</td>
                <td>
                  {it.entity_type ?? "n/a"}
                  {it.entity_id ? ` · ${shorten(it.entity_id)}` : ""}
                </td>
                <td>{shorten(it.user_id)}</td>
                <td>{it.ip_address ?? "n/a"}</td>
                <td className="audit-detail">{formatDetail(it.detail)}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6}>No audit entries.</td>
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
