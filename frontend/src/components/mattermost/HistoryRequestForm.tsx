import { FormEvent, useState } from "react";
import { createHistoryJob } from "../../api/mattermost";
import type { HistoryJob, MattermostChannel } from "../../types";
import { apiErrorLines, localInputToIso } from "../../utils/mattermostAsk";

interface Props {
  channels: MattermostChannel[];
  loading: boolean;
  error: string | null;
  canWrite: boolean;
  onReloadChannels: () => void;
  onCreated: (job: HistoryJob) => void;
}

function toggle(selected: Set<string>, id: string): Set<string> {
  const next = new Set(selected);
  if (next.has(id)) {
    next.delete(id);
  } else {
    next.add(id);
  }
  return next;
}

function selectionSummary(count: number): string {
  if (count === 0) return "No channels selected: every channel the bot belongs to will be pulled.";
  if (count === 1) return "1 channel selected.";
  return `${count} channels selected.`;
}

export default function HistoryRequestForm(props: Props) {
  const { channels, loading, error, canWrite, onReloadChannels, onCreated } = props;
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [startNow, setStartNow] = useState(true);
  const [startAt, setStartAt] = useState("");
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const startIso = startNow ? null : localInputToIso(startAt);
  const startMissing = !startNow && !startIso;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (startMissing) {
      setErrors(["Choose a start time, or pick Now."]);
      return;
    }
    setSaving(true);
    setErrors([]);
    try {
      const job = await createHistoryJob({ channel_ids: [...selected], run_after: startIso });
      setSelected(new Set());
      onCreated(job);
    } catch (err) {
      setErrors(apiErrorLines(err, "Could not schedule the pull."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card">
      <h2>Channels</h2>
      <div className="ask-form-actions">
        <button type="button" onClick={onReloadChannels}>
          Refresh channels
        </button>
      </div>
      {error && <div className="form-error">{error}</div>}
      {loading && <div>Loading...</div>}
      <form onSubmit={onSubmit}>
        <table className="elsets-table">
          <thead>
            <tr>
              <th>Pull</th>
              <th>Display name</th>
              <th>URL name</th>
              <th>Type</th>
              <th>Archived</th>
              <th>History complete</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((c) => (
              <tr key={c.id}>
                <td>
                  <input
                    id={`history-channel-${c.id}`}
                    type="checkbox"
                    checked={selected.has(c.id)}
                    disabled={!canWrite}
                    onChange={() => setSelected((s) => toggle(s, c.id))}
                  />
                  <label htmlFor={`history-channel-${c.id}`} className="visually-hidden">
                    Pull {c.display_name ?? c.name}
                  </label>
                </td>
                <td>{c.display_name ?? "-"}</td>
                <td>{c.name}</td>
                <td>{c.type === "P" ? "Private" : "Public"}</td>
                <td>{c.archived ? "Yes" : "No"}</td>
                <td>{c.history_complete ? "Yes" : "No"}</td>
              </tr>
            ))}
            {!loading && channels.length === 0 && (
              <tr>
                <td colSpan={6}>No channels available.</td>
              </tr>
            )}
          </tbody>
        </table>

        {canWrite && (
          <fieldset className="ask-fieldset">
            <legend>Pull full history</legend>
            <p className="muted">{selectionSummary(selected.size)}</p>
            <label className="ask-checkbox">
              <input
                type="radio"
                name="history-start"
                checked={startNow}
                onChange={() => setStartNow(true)}
              />
              Start now
            </label>
            <label className="ask-checkbox">
              <input
                type="radio"
                name="history-start"
                checked={!startNow}
                onChange={() => setStartNow(false)}
              />
              Start at a chosen time
            </label>
            {!startNow && (
              <label>
                Start time (your local time)
                <input
                  type="datetime-local"
                  value={startAt}
                  onChange={(e) => setStartAt(e.target.value)}
                />
              </label>
            )}
            {errors.length > 0 && (
              <div className="form-error">
                <ul>
                  {errors.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="ask-form-actions">
              <button type="submit" disabled={saving || startMissing}>
                {saving ? "Scheduling..." : "Pull full history"}
              </button>
            </div>
          </fieldset>
        )}
      </form>
    </section>
  );
}
