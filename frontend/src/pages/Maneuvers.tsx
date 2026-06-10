import { FormEvent, useEffect, useState } from "react";
import { listManeuvers } from "../api/maneuvers";
import SortableHeader from "../components/SortableHeader";
import type { Maneuver, ManeuverSortColumn, SortDirection } from "../types";

const PAGE_SIZE = 50;

function formatDateTime(value: string | null): string {
  if (!value) return "n/a";
  return new Date(value).toISOString().replace("T", " ").slice(0, 19);
}

function formatNumber(value: number | null, digits = 3): string {
  if (value === null || value === undefined) return "n/a";
  return value.toFixed(digits);
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

export default function ManeuversPage() {
  const [items, setItems] = useState<Maneuver[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [satNoFilter, setSatNoFilter] = useState<number | undefined>(undefined);
  const [satNoInput, setSatNoInput] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | undefined>(undefined);
  const [typeInput, setTypeInput] = useState("");
  const [sortColumn, setSortColumn] = useState<ManeuverSortColumn>("event_start_time");
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
        const page = await listManeuvers({
          sat_no: satNoFilter,
          mnvr_type: typeFilter,
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
        if (!cancelled) setError(extractErrorMessage(err, "Failed to load maneuvers."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [satNoFilter, typeFilter, offset, sortColumn, sortDirection, reloadToken]);

  function onSortChange(column: ManeuverSortColumn) {
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
    const trimmedSat = satNoInput.trim();
    if (trimmedSat === "") {
      setSatNoFilter(undefined);
    } else {
      const parsed = Number(trimmedSat);
      if (Number.isNaN(parsed)) {
        setError("Satellite number must be numeric.");
        return;
      }
      setSatNoFilter(parsed);
    }
    const trimmedType = typeInput.trim();
    setTypeFilter(trimmedType === "" ? undefined : trimmedType);
    setOffset(0);
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <h1>Maneuvers</h1>
      <p className="muted-paragraph">
        UDL maneuver records uploaded by fusion providers. Auto-refreshing in the background; the
        assistant uses these to contextualise NOTSOs for the same satellites.
      </p>

      <section className="card">
        <form onSubmit={onFilterSubmit} className="filter-form">
          <label>
            Satellite number
            <input
              type="number"
              value={satNoInput}
              onChange={(e) => setSatNoInput(e.target.value)}
              placeholder="e.g. 25544"
            />
          </label>
          <label>
            Maneuver type
            <input
              type="text"
              value={typeInput}
              onChange={(e) => setTypeInput(e.target.value)}
              placeholder="e.g. ESPMV"
            />
          </label>
          <button type="submit">Apply</button>
          <button
            type="button"
            onClick={() => {
              setSatNoInput("");
              setTypeInput("");
              setSatNoFilter(undefined);
              setTypeFilter(undefined);
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
                column="sat_no"
                label="Sat No"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <SortableHeader
                column="event_start_time"
                label="Start"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <SortableHeader
                column="event_stop_time"
                label="Stop"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <SortableHeader
                column="mnvr_type"
                label="Type"
                activeColumn={sortColumn}
                activeDirection={sortDirection}
                onChange={onSortChange}
              />
              <th>Delta-V (m/s)</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.id}>
                <td>{m.sat_no ?? "n/a"}</td>
                <td>{formatDateTime(m.event_start_time)}</td>
                <td>{formatDateTime(m.event_stop_time)}</td>
                <td>{m.mnvr_type ?? "n/a"}</td>
                <td>{formatNumber(m.delta_v)}</td>
                <td>{m.source ?? "n/a"}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6}>No maneuvers to show.</td>
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
