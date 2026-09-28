import { FormEvent, useCallback, useEffect, useState } from "react";
import { deleteProcedure, getProcedure, listProcedures, uploadProcedure } from "../api/procedures";
import type { Procedure, ProcedureContent } from "../types";

function formatDateTime(value: string): string {
  return new Date(value).toISOString().replace("T", " ").slice(0, 19);
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
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

export default function ProceduresPage() {
  const [items, setItems] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  const [selected, setSelected] = useState<ProcedureContent | null>(null);
  const [selectedLoading, setSelectedLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await listProcedures();
      setItems(page.items);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load procedures."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file || !name.trim()) return;
    setUploading(true);
    setError(null);
    try {
      await uploadProcedure(name.trim(), description.trim() || null, file);
      setName("");
      setDescription("");
      setFile(null);
      const fileInput = document.getElementById("procedure-file") as HTMLInputElement | null;
      if (fileInput) fileInput.value = "";
      await load();
    } catch (err) {
      setError(extractErrorMessage(err, "Upload failed."));
    } finally {
      setUploading(false);
    }
  }

  async function onDelete(id: string) {
    if (!globalThis.confirm("Delete this procedure? This cannot be undone.")) return;
    setError(null);
    try {
      await deleteProcedure(id);
      if (selected?.id === id) setSelected(null);
      await load();
    } catch (err) {
      setError(extractErrorMessage(err, "Delete failed."));
    }
  }

  async function onView(id: string) {
    setSelectedLoading(true);
    setError(null);
    try {
      const detail = await getProcedure(id);
      setSelected(detail);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load procedure."));
    } finally {
      setSelectedLoading(false);
    }
  }

  return (
    <div>
      <h1>Procedures</h1>
      <p className="muted-paragraph">
        Upload operations procedures here. The assistant reads them at evaluation time and uses them
        to recommend next-step actions for each NOTSO.
      </p>

      <section className="card">
        <h2>Upload a procedure</h2>
        <form onSubmit={onSubmit} className="ingest-form">
          <label>
            Name
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. NOTSO release cadence"
              required
            />
          </label>
          <label>
            Description (optional)
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="When does this procedure apply?"
            />
          </label>
          <label>
            File
            <input
              id="procedure-file"
              type="file"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              required
            />
          </label>
          <button type="submit" disabled={uploading || !file || !name.trim()}>
            {uploading ? "Uploading..." : "Upload"}
          </button>
        </form>
      </section>

      {error && <div className="form-error">{error}</div>}

      <section className="card">
        <h2>Uploaded procedures</h2>
        {loading && <div>Loading...</div>}
        <table className="elsets-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Filename</th>
              <th>Size</th>
              <th>Uploaded</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id}>
                <td>
                  <strong>{p.name}</strong>
                  {p.description && <div className="muted">{p.description}</div>}
                </td>
                <td>{p.filename}</td>
                <td>{formatSize(p.size_bytes)}</td>
                <td>{formatDateTime(p.created_at)}</td>
                <td>
                  <button type="button" onClick={() => onView(p.id)}>
                    View
                  </button>{" "}
                  <a href={`/api/v1/procedures/${p.id}/download`} target="_blank" rel="noreferrer">
                    Download
                  </a>{" "}
                  <button type="button" onClick={() => onDelete(p.id)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={5}>No procedures uploaded yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      {selectedLoading && <div>Loading procedure...</div>}
      {selected && (
        <section className="card">
          <h2>{selected.name}</h2>
          <div className="muted">
            {selected.filename} &middot; {formatSize(selected.size_bytes)} &middot;{" "}
            {selected.content_type}
          </div>
          {selected.description && <p>{selected.description}</p>}
          {selected.content !== null ? (
            <pre
              style={{
                whiteSpace: "pre-wrap",
                background: "#f5f7fa",
                padding: "12px",
                borderRadius: "4px",
                maxHeight: "400px",
                overflow: "auto",
              }}
            >
              {selected.content}
              {selected.content_truncated && "\n\n... (truncated)"}
            </pre>
          ) : (
            <p className="muted">Inline preview not available for this file type. Use Download.</p>
          )}
          <button type="button" onClick={() => setSelected(null)}>
            Close
          </button>
        </section>
      )}
    </div>
  );
}
