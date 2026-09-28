import { useCallback, useEffect, useRef, useState } from "react";
import { deleteAsk, getAsk, listAsks, runAsk, unscheduleAsk } from "../../api/mattermost";
import type { Ask } from "../../types";
import {
  apiErrorMessage,
  ASK_POLL_INTERVAL_MS,
  shouldKeepPollingAsk,
} from "../../utils/mattermostAsk";
import AskForm from "./AskForm";
import AskResults from "./AskResults";
import AskRow, { AskRowActions } from "./AskRow";
import type { ChannelsState } from "./useMattermostChannels";

interface Props {
  canWrite: boolean;
  channels: ChannelsState;
}

type Editing = { mode: "new" } | { mode: "edit"; ask: Ask } | null;

function replaceAsk(list: Ask[], updated: Ask): Ask[] {
  return list.map((a) => (a.id === updated.id ? updated : a));
}

export default function AsksTab({ canWrite, channels }: Props) {
  const [asks, setAsks] = useState<Ask[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [resultsToken, setResultsToken] = useState(0);
  // Ask id -> time (ms) polling started, for asks queued by "Run now".
  const [polling, setPolling] = useState<Record<string, number>>({});
  const pollingRef = useRef(polling);
  pollingRef.current = polling;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAsks(await listAsks());
    } catch (err) {
      setError(apiErrorMessage(err, "Failed to load asks."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const pollOnce = useCallback(async () => {
    const entries = Object.entries(pollingRef.current);
    const done: string[] = [];
    for (const [id, startedAt] of entries) {
      try {
        const fresh = await getAsk(id);
        setAsks((list) => replaceAsk(list, fresh));
        if (!shouldKeepPollingAsk(fresh.last_status, startedAt, Date.now())) done.push(id);
      } catch {
        done.push(id);
      }
    }
    if (done.length === 0) return;
    setPolling((current) => {
      const next = { ...current };
      for (const id of done) delete next[id];
      return next;
    });
    setResultsToken((t) => t + 1);
  }, []);

  const isPolling = Object.keys(polling).length > 0;
  useEffect(() => {
    if (!isPolling) return;
    const handle = globalThis.setInterval(pollOnce, ASK_POLL_INTERVAL_MS);
    return () => globalThis.clearInterval(handle);
  }, [isPolling, pollOnce]);

  async function act(action: () => Promise<Ask>, fallback: string): Promise<Ask | null> {
    setError(null);
    try {
      const updated = await action();
      setAsks((list) => replaceAsk(list, updated));
      return updated;
    } catch (err) {
      setError(apiErrorMessage(err, fallback));
      return null;
    }
  }

  const actions: AskRowActions = {
    onRun: async (ask) => {
      const updated = await act(() => runAsk(ask.id), "Could not queue the run.");
      if (updated) setPolling((current) => ({ ...current, [ask.id]: Date.now() }));
    },
    onSchedule: (ask, iso) => {
      act(() => runAsk(ask.id, iso), "Could not schedule the ask.");
    },
    onUnschedule: (ask) => {
      act(() => unscheduleAsk(ask.id), "Could not unschedule the ask.");
    },
    onEdit: (ask) => setEditing({ mode: "edit", ask }),
    onDelete: async (ask) => {
      if (!globalThis.confirm(`Delete the ask "${ask.name}" and its results?`)) return;
      setError(null);
      try {
        await deleteAsk(ask.id);
        setAsks((list) => list.filter((a) => a.id !== ask.id));
        if (selectedId === ask.id) setSelectedId(null);
      } catch (err) {
        setError(apiErrorMessage(err, "Delete failed."));
      }
    },
    onShowResults: (ask) => setSelectedId(ask.id),
  };

  function onSaved(saved: Ask) {
    setAsks((list) =>
      list.some((a) => a.id === saved.id) ? replaceAsk(list, saved) : [saved, ...list],
    );
    setEditing(null);
  }

  const selected = asks.find((a) => a.id === selectedId) ?? null;

  return (
    <>
      {editing && canWrite && (
        <AskForm
          key={editing.mode === "edit" ? editing.ask.id : "new"}
          initial={editing.mode === "edit" ? editing.ask : null}
          channels={channels.channels}
          onSaved={onSaved}
          onCancel={() => setEditing(null)}
        />
      )}

      <section className="card">
        <h2>Saved asks</h2>
        <p className="muted">
          Runs are queued and picked up by the background loop within about a minute. Times are UTC.
        </p>
        <div className="ask-form-actions">
          {canWrite && (
            <button type="button" onClick={() => setEditing({ mode: "new" })} disabled={!!editing}>
              New ask
            </button>
          )}
          <button type="button" onClick={load}>
            Refresh
          </button>
        </div>
        {channels.error && canWrite && (
          <div className="form-error">Channel list unavailable: {channels.error}</div>
        )}
        {error && <div className="form-error">{error}</div>}
        {loading && <div>Loading...</div>}
        <table className="elsets-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Scope</th>
              <th>Last run</th>
              <th>Results</th>
              <th>Next run</th>
              <th>Refresh</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {asks.map((ask) => (
              <AskRow
                key={ask.id}
                ask={ask}
                canWrite={canWrite}
                polling={ask.id in polling}
                selected={ask.id === selectedId}
                actions={actions}
              />
            ))}
            {!loading && asks.length === 0 && (
              <tr>
                <td colSpan={7}>No asks saved yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      {selected && (
        <AskResults
          key={selected.id}
          ask={selected}
          reloadToken={resultsToken}
          onClose={() => setSelectedId(null)}
        />
      )}
    </>
  );
}
