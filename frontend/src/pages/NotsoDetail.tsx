import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getNotso } from "../api/notsos";
import type { NotsoDetail as NotsoDetailType } from "../types";

function formatField(value: unknown): string {
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "n/a";
  return new Date(value).toISOString().replace("T", " ").slice(0, 19);
}

export default function NotsoDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [item, setItem] = useState<NotsoDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await getNotso(id!);
        if (!cancelled) setItem(data);
      } catch (err) {
        if (!cancelled) {
          if (err && typeof err === "object" && "response" in err) {
            const status = (err as { response?: { status?: number } }).response?.status;
            if (status === 404) {
              setError("NOTSO not found.");
            } else {
              setError("Failed to load NOTSO.");
            }
          } else {
            setError("Failed to load NOTSO.");
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) return <div>Loading...</div>;
  if (error) return <div className="form-error">{error}</div>;
  if (!item) return null;

  return (
    <div>
      <Link to="/notsos" className="back-link">
        &larr; Back to NOTSOs
      </Link>
      <h1>{item.notice_id ?? "NOTSO"}</h1>

      <section className="card">
        <h2>Identification</h2>
        <dl className="detail-grid">
          <dt>Internal ID</dt>
          <dd>{item.id}</dd>
          <dt>UDL ID</dt>
          <dd>{formatField(item.udl_id)}</dd>
          <dt>Notice ID</dt>
          <dd>{formatField(item.notice_id)}</dd>
          <dt>Message type</dt>
          <dd>{formatField(item.msg_type)}</dd>
          <dt>Source</dt>
          <dd>{formatField(item.source)}</dd>
          <dt>Data mode</dt>
          <dd>{formatField(item.data_mode)}</dd>
          <dt>Classification</dt>
          <dd>{formatField(item.classification_marking)}</dd>
        </dl>
      </section>

      <section className="card">
        <h2>Effective window</h2>
        <dl className="detail-grid">
          <dt>From</dt>
          <dd>{formatDateTime(item.effective_from)}</dd>
          <dt>Until</dt>
          <dd>{formatDateTime(item.effective_until)}</dd>
          <dt>UDL created</dt>
          <dd>{formatDateTime(item.udl_created_at)}</dd>
        </dl>
      </section>

      <section className="card">
        <h2>Content</h2>
        <dl className="detail-grid">
          <dt>Subject</dt>
          <dd>{formatField(item.subject)}</dd>
          <dt>Region</dt>
          <dd>{formatField(item.region)}</dd>
          <dt>Satellite number</dt>
          <dd>{formatField(item.sat_no)}</dd>
        </dl>
        {item.description && (
          <div>
            <h3>Description</h3>
            <pre className="notso-description">{item.description}</pre>
          </div>
        )}
      </section>

      <section className="card">
        <h2>Raw UDL payload</h2>
        <pre className="raw-json">{JSON.stringify(item.raw, null, 2)}</pre>
      </section>
    </div>
  );
}
