import { useState } from "react";
import type { Ask } from "../../types";
import {
  formatOptionalDateTime,
  formatRefresh,
  localInputToIso,
  scopeLabel,
  statusPillClass,
} from "../../utils/mattermostAsk";

export interface AskRowActions {
  onRun: (ask: Ask) => void;
  onSchedule: (ask: Ask, runAtIso: string) => void;
  onUnschedule: (ask: Ask) => void;
  onEdit: (ask: Ask) => void;
  onDelete: (ask: Ask) => void;
  onShowResults: (ask: Ask) => void;
}

interface Props {
  ask: Ask;
  canWrite: boolean;
  polling: boolean;
  selected: boolean;
  actions: AskRowActions;
}

function WriteActions({ ask, actions }: { ask: Ask; actions: AskRowActions }) {
  const [runAt, setRunAt] = useState("");
  const iso = localInputToIso(runAt);
  const inputId = `ask-schedule-${ask.id}`;

  return (
    <div className="ask-actions">
      <button type="button" onClick={() => actions.onRun(ask)}>
        Run now
      </button>
      <label htmlFor={inputId} className="visually-hidden">
        Schedule {ask.name} at (your local time)
      </label>
      <input
        id={inputId}
        type="datetime-local"
        value={runAt}
        onChange={(e) => setRunAt(e.target.value)}
      />
      <button
        type="button"
        disabled={!iso}
        onClick={() => {
          if (iso) actions.onSchedule(ask, iso);
          setRunAt("");
        }}
      >
        Schedule
      </button>
      <button type="button" disabled={!ask.next_run_at} onClick={() => actions.onUnschedule(ask)}>
        Unschedule
      </button>
      <button type="button" onClick={() => actions.onEdit(ask)}>
        Edit
      </button>
      <button type="button" onClick={() => actions.onDelete(ask)}>
        Delete
      </button>
    </div>
  );
}

export default function AskRow({ ask, canWrite, polling, selected, actions }: Props) {
  return (
    <tr className={selected ? "ask-row-selected" : undefined}>
      <td>
        <strong>{ask.name}</strong>
        {ask.question && <div className="muted">{ask.question}</div>}
        {ask.last_error && <div className="ask-error-text">{ask.last_error}</div>}
      </td>
      <td>{scopeLabel(ask.spec.scope)}</td>
      <td>
        <div>{formatOptionalDateTime(ask.last_run_at, "Never")}</div>
        {ask.last_status && (
          <span className={statusPillClass(ask.last_status)}>{ask.last_status}</span>
        )}
        {polling && <div className="muted">Waiting for the run...</div>}
      </td>
      <td>{ask.result_count}</td>
      <td>{formatOptionalDateTime(ask.next_run_at, "Not scheduled")}</td>
      <td>{formatRefresh(ask.refresh_minutes)}</td>
      <td>
        <button type="button" onClick={() => actions.onShowResults(ask)}>
          {selected ? "Showing results" : "Results"}
        </button>
        {canWrite && <WriteActions ask={ask} actions={actions} />}
      </td>
    </tr>
  );
}
