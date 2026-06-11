import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  createShiftNote,
  deleteShiftNote,
  generateShiftSummary,
  getShiftSummary,
  listShiftNotes,
  repolishShiftNote,
  shiftExportUrl,
  updateShiftNote,
} from "../api/shift";
import type { ShiftNote, ShiftSummary } from "../types";

function todayUtcIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatTime(value: string): string {
  return new Date(value).toISOString().slice(11, 19) + "Z";
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

interface NoteRowProps {
  note: ShiftNote;
  onSaved: (n: ShiftNote) => void;
  onDeleted: (id: string) => void;
  onError: (msg: string) => void;
}

function NoteRow({ note, onSaved, onDeleted, onError }: NoteRowProps) {
  const [editing, setEditing] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [editText, setEditText] = useState(note.polished_text ?? note.raw_text);
  const [busy, setBusy] = useState(false);

  async function onSave() {
    setBusy(true);
    try {
      const updated = await updateShiftNote(note.id, editText);
      onSaved(updated);
      setEditing(false);
    } catch (err) {
      onError(extractErrorMessage(err, "Failed to save."));
    } finally {
      setBusy(false);
    }
  }

  async function onRepolish() {
    setBusy(true);
    try {
      const updated = await repolishShiftNote(note.id);
      onSaved(updated);
      setEditText(updated.polished_text ?? updated.raw_text);
    } catch (err) {
      onError(extractErrorMessage(err, "Re-polish failed."));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!window.confirm("Delete this entry?")) return;
    setBusy(true);
    try {
      await deleteShiftNote(note.id);
      onDeleted(note.id);
    } catch (err) {
      onError(extractErrorMessage(err, "Delete failed."));
    } finally {
      setBusy(false);
    }
  }

  const display = note.polished_text ?? note.raw_text;
  const hasError = !!note.polish_error;

  return (
    <li className="shift-note">
      <div className="shift-note-head">
        <span className="shift-note-time">{formatTime(note.created_at)}</span>
        <div className="shift-note-actions">
          <button type="button" onClick={() => setShowRaw((s) => !s)} disabled={busy}>
            {showRaw ? "Hide raw" : "Show raw"}
          </button>
          {!editing && (
            <button type="button" onClick={() => setEditing(true)} disabled={busy}>
              Edit
            </button>
          )}
          <button type="button" onClick={onRepolish} disabled={busy}>
            Re-polish
          </button>
          <button type="button" onClick={onDelete} disabled={busy}>
            Delete
          </button>
        </div>
      </div>
      {hasError && (
        <div className="form-error">Polish failed: {note.polish_error}. Showing raw text.</div>
      )}
      {editing ? (
        <>
          <textarea
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            rows={4}
            className="shift-note-edit"
          />
          <div className="shift-note-actions">
            <button type="button" onClick={onSave} disabled={busy}>
              {busy ? "Saving..." : "Save"}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setEditText(note.polished_text ?? note.raw_text);
              }}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <p className="shift-note-body">{display}</p>
      )}
      {showRaw && !editing && (
        <div className="shift-note-raw">
          <span className="muted">Raw input:</span>
          <p>{note.raw_text}</p>
        </div>
      )}
    </li>
  );
}

export default function ShiftLogPage() {
  const [shiftDate, setShiftDate] = useState<string>(todayUtcIso());
  const [notes, setNotes] = useState<ShiftNote[]>([]);
  const [summary, setSummary] = useState<ShiftSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [draft, setDraft] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async (date: string) => {
    setLoading(true);
    setError(null);
    try {
      const [noteList, sum] = await Promise.all([listShiftNotes(date), getShiftSummary(date)]);
      setNotes(noteList.items);
      setSummary(sum);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load shift log."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(shiftDate);
  }, [shiftDate, load]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createShiftNote(text, shiftDate);
      setNotes((prev) => [...prev, created]);
      setDraft("");
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to save note."));
    } finally {
      setSubmitting(false);
    }
  }

  async function onGenerateSummary() {
    setGenerating(true);
    setError(null);
    try {
      const result = await generateShiftSummary(shiftDate);
      setSummary(result);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to generate summary."));
    } finally {
      setGenerating(false);
    }
  }

  function onNoteSaved(updated: ShiftNote) {
    setNotes((prev) => prev.map((n) => (n.id === updated.id ? updated : n)));
  }

  function onNoteDeleted(id: string) {
    setNotes((prev) => prev.filter((n) => n.id !== id));
  }

  const hasNotes = notes.length > 0;

  return (
    <div>
      <div className="dashboard-header">
        <div>
          <h1>Shift log</h1>
          <p className="muted-paragraph">
            Capture observations as you go. Claude tidies your words into a professional record.
            Generate the end-of-shift narrative when you're ready to hand over.
          </p>
        </div>
        <div className="shift-toolbar">
          <label className="shift-date-picker">
            Shift date
            <input
              type="date"
              value={shiftDate}
              onChange={(e) => setShiftDate(e.target.value || todayUtcIso())}
            />
          </label>
          <a href={shiftExportUrl(shiftDate, "md")} target="_blank" rel="noreferrer">
            Export .md
          </a>
          <a href={shiftExportUrl(shiftDate, "html")} target="_blank" rel="noreferrer">
            Export .html
          </a>
        </div>
      </div>

      {error && <div className="form-error">{error}</div>}

      <section className="card shift-entry">
        <h2>New entry</h2>
        <form onSubmit={onSubmit}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            placeholder="Type whatever you want, however you want. Claude will tidy it up."
            disabled={submitting}
          />
          <div className="shift-entry-actions">
            <span className="muted">{draft.length} chars</span>
            <button type="submit" disabled={submitting || !draft.trim()}>
              {submitting ? "Saving..." : "Add to log"}
            </button>
          </div>
        </form>
      </section>

      <section className="card">
        <h2>Timeline &middot; {notes.length}</h2>
        {loading && <div>Loading...</div>}
        {!loading && !hasNotes && <p className="muted">No entries yet for this shift.</p>}
        <ul className="shift-notes-list">
          {notes.map((n) => (
            <NoteRow
              key={n.id}
              note={n}
              onSaved={onNoteSaved}
              onDeleted={onNoteDeleted}
              onError={setError}
            />
          ))}
        </ul>
      </section>

      <section className="card shift-summary-card">
        <div className="shift-summary-head">
          <h2>End-of-shift narrative</h2>
          <button type="button" onClick={onGenerateSummary} disabled={generating || !hasNotes}>
            {generating ? "Composing..." : summary ? "Regenerate" : "Generate"}
          </button>
        </div>
        {!hasNotes && <p className="muted">Add at least one entry to generate a narrative.</p>}
        {summary?.error && <div className="form-error">Generation error: {summary.error}</div>}
        {summary && (
          <>
            <pre className="shift-summary-body">{summary.narrative}</pre>
            <div className="muted">
              {summary.model} &middot; generated {new Date(summary.created_at).toISOString()}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
