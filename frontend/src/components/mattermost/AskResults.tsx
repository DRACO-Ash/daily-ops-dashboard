import { useCallback, useEffect, useState } from "react";
import { downloadAskResultsCsv, listAskResults } from "../../api/mattermost";
import type { Ask, AskResult } from "../../types";
import {
  apiErrorMessage,
  downloadFilename,
  formatDateTime,
  formatOptionalDateTime,
} from "../../utils/mattermostAsk";

const PAGE_SIZE = 50;

interface Props {
  ask: Ask;
  reloadToken: number;
  onClose: () => void;
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function ThreadCell({ row }: { row: AskResult }) {
  return (
    <td>
      <div>{row.thread_title ?? row.thread_id}</div>
      {row.thread_started_at && (
        <div className="muted">started {formatDateTime(row.thread_started_at)}</div>
      )}
    </td>
  );
}

function ResultRow({ row }: { row: AskResult }) {
  return (
    <tr>
      <td>{formatDateTime(row.posted_at)}</td>
      <td>
        #{row.channel_name ?? row.channel_id}
        {row.channel_archived && <div className="muted">archived</div>}
      </td>
      <td>{row.author ? `@${row.author}` : "-"}</td>
      <ThreadCell row={row} />
      <td>{row.extracted ?? "-"}</td>
      <td className="ask-excerpt">{row.excerpt}</td>
      <td>
        {row.permalink ? (
          <a href={row.permalink} target="_blank" rel="noopener noreferrer">
            Open in Mattermost
          </a>
        ) : (
          "-"
        )}
      </td>
    </tr>
  );
}

export default function AskResults({ ask, reloadToken, onClose }: Props) {
  const [items, setItems] = useState<AskResult[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await listAskResults(ask.id, PAGE_SIZE, offset);
      setItems(page.items);
      setTotal(page.total);
    } catch (err) {
      setError(apiErrorMessage(err, "Failed to load results."));
    } finally {
      setLoading(false);
    }
  }, [ask.id, offset]);

  useEffect(() => {
    load();
  }, [load, reloadToken]);

  async function onDownload() {
    setDownloading(true);
    setError(null);
    try {
      const { blob, disposition } = await downloadAskResultsCsv(ask.id);
      saveBlob(blob, downloadFilename(disposition, ask.name));
    } catch (err) {
      setError(apiErrorMessage(err, "Download failed."));
    } finally {
      setDownloading(false);
    }
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="card">
      <h2>Results: {ask.name}</h2>
      <p className="muted">
        Last run {formatOptionalDateTime(ask.last_run_at, "never")}. Times are UTC.
      </p>
      <div className="ask-form-actions">
        <button type="button" onClick={onDownload} disabled={downloading || total === 0}>
          {downloading ? "Preparing..." : "Download CSV"}
        </button>
        <button type="button" onClick={load}>
          Refresh
        </button>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      {error && <div className="form-error">{error}</div>}
      {loading && <div>Loading...</div>}
      <table className="elsets-table">
        <thead>
          <tr>
            <th>Posted (UTC)</th>
            <th>Channel</th>
            <th>Author</th>
            <th>Thread</th>
            <th>Extracted</th>
            <th>Excerpt</th>
            <th>Link</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <ResultRow key={row.mm_post_id} row={row} />
          ))}
          {!loading && items.length === 0 && (
            <tr>
              <td colSpan={7}>No results yet. Run the ask to pull matching posts.</td>
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
  );
}
