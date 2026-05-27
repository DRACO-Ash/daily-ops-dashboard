import { FormEvent, useEffect, useState } from "react";
import { listElsets, triggerElsetIngest } from "../api/elsets";
import type { Elset, ElsetIngestResponse } from "../types";

const PAGE_SIZE = 50;

function formatNumber(value: number | null, digits = 6): string {
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

export default function ElsetsPage() {
  const [items, setItems] = useState<Elset[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [satNoFilter, setSatNoFilter] = useState<number | undefined>(undefined);
  const [satNoInput, setSatNoInput] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [ingestEpochGte, setIngestEpochGte] = useState("");
  const [ingestSatNo, setIngestSatNo] = useState("");
  const [ingestMaxResults, setIngestMaxResults] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState<ElsetIngestResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const page = await listElsets({
          sat_no: satNoFilter,
          limit: PAGE_SIZE,
          offset,
        });
        if (!cancelled) {
          setItems(page.items);
          setTotal(page.total);
        }
      } catch (err) {
        if (!cancelled) {
          setError(extractErrorMessage(err, "Failed to load element sets."));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [satNoFilter, offset, reloadToken]);

  function onFilterSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = satNoInput.trim();
    if (trimmed === "") {
      setSatNoFilter(undefined);
      setOffset(0);
      return;
    }
    const parsed = Number(trimmed);
    if (Number.isNaN(parsed)) {
      setError("Satellite number must be numeric.");
      return;
    }
    setSatNoFilter(parsed);
    setOffset(0);
  }

  async function onIngestSubmit(event: FormEvent) {
    event.preventDefault();
    if (!ingestEpochGte) {
      setError("Epoch (since) is required for ingest.");
      return;
    }
    setIngesting(true);
    setIngestResult(null);
    setError(null);
    try {
      const result = await triggerElsetIngest({
        epoch_gte: new Date(ingestEpochGte).toISOString(),
        sat_no: ingestSatNo ? Number(ingestSatNo) : undefined,
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
      <h1>Element sets</h1>

      <section className="card">
        <h2>Trigger UDL ingest</h2>
        <form onSubmit={onIngestSubmit} className="ingest-form">
          <label>
            Epoch since
            <input
              type="datetime-local"
              value={ingestEpochGte}
              onChange={(e) => setIngestEpochGte(e.target.value)}
              required
            />
          </label>
          <label>
            Satellite number (optional)
            <input
              type="number"
              value={ingestSatNo}
              onChange={(e) => setIngestSatNo(e.target.value)}
              placeholder="e.g. 25544"
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
            Pulled {ingestResult.pulled} &middot; Inserted {ingestResult.inserted} &middot; Updated {ingestResult.updated} &middot; Skipped {ingestResult.skipped}
          </div>
        )}
      </section>

      <section className="card">
        <form onSubmit={onFilterSubmit} className="filter-form">
          <label>
            Filter by satellite number
            <input
              type="number"
              value={satNoInput}
              onChange={(e) => setSatNoInput(e.target.value)}
              placeholder="e.g. 25544"
            />
          </label>
          <button type="submit">Apply</button>
          <button
            type="button"
            onClick={() => {
              setSatNoInput("");
              setSatNoFilter(undefined);
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
              <th>Sat No</th>
              <th>Epoch</th>
              <th>Mean motion</th>
              <th>Eccentricity</th>
              <th>Inclination</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id}>
                <td>{it.sat_no}</td>
                <td>
                  {new Date(it.epoch).toISOString().replace("T", " ").slice(0, 19)}
                </td>
                <td>{formatNumber(it.mean_motion)}</td>
                <td>{formatNumber(it.eccentricity)}</td>
                <td>{formatNumber(it.inclination, 4)}</td>
                <td>{it.source ?? "n/a"}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6}>No element sets to show.</td>
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
