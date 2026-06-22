import { FormEvent, useCallback, useEffect, useState } from "react";
import { listMattermostMessages } from "../api/mattermost";
import type { MattermostMessage } from "../types";

const PAGE_SIZE = 100;

function formatDateTime(value: string): string {
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

export default function MattermostPage() {
  const [items, setItems] = useState<MattermostMessage[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [channelFilter, setChannelFilter] = useState<string | undefined>(undefined);
  const [channelInput, setChannelInput] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await listMattermostMessages({
        channel_id: channelFilter,
        limit: PAGE_SIZE,
        offset,
      });
      setItems(page.items);
      setTotal(page.total);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load Mattermost messages."));
    } finally {
      setLoading(false);
    }
  }, [channelFilter, offset]);

  useEffect(() => {
    load();
  }, [load, reloadToken]);

  function onFilterSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = channelInput.trim();
    setChannelFilter(trimmed === "" ? undefined : trimmed);
    setOffset(0);
  }

  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <h1>Comms</h1>
      <p className="muted-paragraph">
        Recent messages pulled from the configured Mattermost channels. The assistant uses these as
        soft context when evaluating each NOTSO.
      </p>

      <section className="card">
        <form onSubmit={onFilterSubmit} className="filter-form">
          <label>
            Channel ID (filter)
            <input
              type="text"
              value={channelInput}
              onChange={(e) => setChannelInput(e.target.value)}
              placeholder="Mattermost channel ID"
            />
          </label>
          <button type="submit">Apply</button>
          <button
            type="button"
            onClick={() => {
              setChannelInput("");
              setChannelFilter(undefined);
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

        {!loading && items.length === 0 && (
          <p className="muted">
            No messages yet. Configure <code>MATTERMOST_CHANNEL_IDS</code> in your .env and make
            sure the bot account is a member of those channels.
          </p>
        )}

        <ul className="comms-list">
          {items.map((m) => (
            <li key={m.id} className="comms-item">
              <div className="comms-head">
                <span className="comms-channel">#{m.channel_name ?? m.channel_id}</span>
                <span className="comms-author">@{m.user_display_name ?? m.user_id}</span>
                <span className="comms-time">{formatDateTime(m.posted_at)}</span>
              </div>
              <p className="comms-body">{m.message}</p>
            </li>
          ))}
        </ul>

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
