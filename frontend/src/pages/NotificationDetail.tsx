import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getNotification } from "../api/notifications";
import AssistantPanel from "../components/AssistantPanel";
import type { NotificationDetail as NotificationDetailType } from "../types";

interface NotsoImage {
  id?: string;
  filename?: string;
  caption?: string;
  url?: string;
}

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

function parseImageMetadata(raw: Record<string, unknown> | null | undefined): NotsoImage[] {
  if (!raw) return [];
  const msgBody = (raw as Record<string, unknown>)["msgBody"];
  if (!msgBody || typeof msgBody !== "object") return [];
  const value = (msgBody as Record<string, unknown>)["NOTSO_Image_Metadata"];
  if (typeof value !== "string") return Array.isArray(value) ? (value as NotsoImage[]) : [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? (parsed as NotsoImage[]) : [];
  } catch {
    return [];
  }
}

function statusClass(status: string | null): string {
  if (!status) return "status-pill";
  return `status-pill status-${status.toLowerCase()}`;
}

export default function NotificationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [item, setItem] = useState<NotificationDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await getNotification(id!);
        if (!cancelled) setItem(data);
      } catch (err) {
        if (!cancelled) {
          if (err && typeof err === "object" && "response" in err) {
            const status = (err as { response?: { status?: number } }).response?.status;
            if (status === 404) {
              setError("Notification not found.");
            } else {
              setError("Failed to load notification.");
            }
          } else {
            setError("Failed to load notification.");
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

  const images = parseImageMetadata(item.raw);
  const satIds = item.sat_ids && item.sat_ids.length > 0 ? item.sat_ids.join(", ") : null;

  return (
    <div>
      <Link to="/notifications" className="back-link">
        &larr; Back to notifications
      </Link>
      <h1>{item.notso_identifier ?? item.notice_id ?? "Notification"}</h1>
      {item.event_class && <p className="detail-subtitle">{item.event_class}</p>}

      <AssistantPanel notificationId={item.id} />

      <section className="card">
        <h2>Status</h2>
        <dl className="detail-grid">
          <dt>Status</dt>
          <dd>
            {item.status ? <span className={statusClass(item.status)}>{item.status}</span> : "n/a"}
          </dd>
          <dt>Event type</dt>
          <dd>{formatField(item.event_type)}</dd>
          <dt>Message type</dt>
          <dd>{formatField(item.msg_type)}</dd>
          <dt>Classification</dt>
          <dd>{formatField(item.classification_marking)}</dd>
          <dt>Data mode</dt>
          <dd>{formatField(item.data_mode)}</dd>
        </dl>
      </section>

      <section className="card">
        <h2>Identification</h2>
        <dl className="detail-grid">
          <dt>Notice</dt>
          <dd>{formatField(item.notso_identifier ?? item.notice_id)}</dd>
          <dt>Event ID</dt>
          <dd>{formatField(item.event_id)}</dd>
          <dt>UDL ID</dt>
          <dd>{formatField(item.udl_id)}</dd>
          <dt>Source</dt>
          <dd>{formatField(item.source)}</dd>
          <dt>Origin network</dt>
          <dd>{formatField(item.orig_network)}</dd>
          <dt>Created by</dt>
          <dd>{formatField(item.created_by)}</dd>
          <dt>Author</dt>
          <dd>{formatField(item.company_name)}</dd>
          {item.notso_link && (
            <>
              <dt>Source link</dt>
              <dd>
                <a href={item.notso_link} target="_blank" rel="noreferrer">
                  {item.notso_link}
                </a>
              </dd>
            </>
          )}
        </dl>
      </section>

      <section className="card">
        <h2>Timing</h2>
        <dl className="detail-grid">
          <dt>UDL created</dt>
          <dd>{formatDateTime(item.udl_created_at)}</dd>
          <dt>Published</dt>
          <dd>{formatDateTime(item.publish_date)}</dd>
          <dt>Effective from</dt>
          <dd>{formatDateTime(item.effective_from)}</dd>
          <dt>Effective until</dt>
          <dd>{formatDateTime(item.effective_until)}</dd>
        </dl>
      </section>

      <section className="card">
        <h2>Associated objects</h2>
        <dl className="detail-grid">
          <dt>Satellite numbers</dt>
          <dd>{satIds ?? (item.sat_no !== null ? String(item.sat_no) : "n/a")}</dd>
          <dt>Region</dt>
          <dd>{formatField(item.region)}</dd>
        </dl>
      </section>

      {item.description && (
        <section className="card">
          <h2>Event description</h2>
          <pre className="notso-description">{item.description}</pre>
        </section>
      )}

      {images.length > 0 && (
        <section className="card">
          <h2>Source artefacts ({images.length})</h2>
          <ul className="image-list">
            {images.map((img, idx) => (
              <li key={img.id ?? idx}>
                {img.url ? (
                  <a href={img.url} target="_blank" rel="noreferrer">
                    {img.filename ?? img.url}
                  </a>
                ) : (
                  <span>{img.filename ?? "(unnamed artefact)"}</span>
                )}
                {img.caption && <span className="image-caption"> &middot; {img.caption}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>Raw UDL payload</h2>
        <pre className="raw-json">{JSON.stringify(item.raw, null, 2)}</pre>
      </section>
    </div>
  );
}
