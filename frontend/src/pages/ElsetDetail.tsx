import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getElset } from "../api/elsets";
import type { ElsetDetail as ElsetDetailType } from "../types";

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

export default function ElsetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [item, setItem] = useState<ElsetDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await getElset(id!);
        if (!cancelled) setItem(data);
      } catch (err) {
        if (!cancelled) {
          if (err && typeof err === "object" && "response" in err) {
            const status = (err as { response?: { status?: number } }).response?.status;
            if (status === 404) {
              setError("Element set not found.");
            } else {
              setError("Failed to load element set.");
            }
          } else {
            setError("Failed to load element set.");
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
      <Link to="/elsets" className="back-link">
        &larr; Back to element sets
      </Link>
      <h1>Element set {item.sat_no}</h1>

      <section className="card">
        <h2>Identification</h2>
        <dl className="detail-grid">
          <dt>Internal ID</dt>
          <dd>{item.id}</dd>
          <dt>UDL ID</dt>
          <dd>{formatField(item.udl_id)}</dd>
          <dt>Satellite number</dt>
          <dd>{item.sat_no}</dd>
          <dt>Epoch</dt>
          <dd>{formatDateTime(item.epoch)}</dd>
          <dt>Source</dt>
          <dd>{formatField(item.source)}</dd>
          <dt>Data mode</dt>
          <dd>{formatField(item.data_mode)}</dd>
          <dt>Classification</dt>
          <dd>{formatField(item.classification_marking)}</dd>
        </dl>
      </section>

      <section className="card">
        <h2>Orbital elements</h2>
        <dl className="detail-grid">
          <dt>Mean motion</dt>
          <dd>{formatField(item.mean_motion)}</dd>
          <dt>Eccentricity</dt>
          <dd>{formatField(item.eccentricity)}</dd>
          <dt>Inclination</dt>
          <dd>{formatField(item.inclination)}</dd>
          <dt>RAAN</dt>
          <dd>{formatField(item.raan)}</dd>
          <dt>Argument of perigee</dt>
          <dd>{formatField(item.arg_of_perigee)}</dd>
          <dt>Mean anomaly</dt>
          <dd>{formatField(item.mean_anomaly)}</dd>
          <dt>Revolution number</dt>
          <dd>{formatField(item.rev_no)}</dd>
          <dt>Bstar</dt>
          <dd>{formatField(item.bstar)}</dd>
          <dt>Semi-major axis</dt>
          <dd>{formatField(item.semi_major_axis)}</dd>
          <dt>Period</dt>
          <dd>{formatField(item.period)}</dd>
          <dt>Apogee</dt>
          <dd>{formatField(item.apogee)}</dd>
          <dt>Perigee</dt>
          <dd>{formatField(item.perigee)}</dd>
        </dl>
      </section>

      {(item.line1 || item.line2) && (
        <section className="card">
          <h2>Two-Line Element</h2>
          <pre className="tle">{item.line1 ?? ""}{"\n"}{item.line2 ?? ""}</pre>
        </section>
      )}

      <section className="card">
        <h2>Raw UDL payload</h2>
        <pre className="raw-json">{JSON.stringify(item.raw, null, 2)}</pre>
      </section>
    </div>
  );
}
