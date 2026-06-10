import { useEffect, useState } from "react";
import { getEvaluation, runEvaluation } from "../api/assistant";
import type { AssistantEvaluation, NextAction } from "../types";

interface AssistantPanelProps {
  notificationId: string;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "n/a";
  return new Date(value).toISOString().replace("T", " ").slice(0, 19);
}

function urgencyClass(urgency: string): string {
  const lower = urgency.toLowerCase();
  if (lower === "high") return "urgency-pill urgency-high";
  if (lower === "medium") return "urgency-pill urgency-medium";
  if (lower === "low") return "urgency-pill urgency-low";
  return "urgency-pill";
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

export default function AssistantPanel({ notificationId }: AssistantPanelProps) {
  const [evaluation, setEvaluation] = useState<AssistantEvaluation | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const existing = await getEvaluation(notificationId);
        if (!cancelled) setEvaluation(existing);
      } catch (err) {
        if (!cancelled) setError(extractErrorMessage(err, "Failed to load assistant evaluation."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [notificationId]);

  async function onRun() {
    setRunning(true);
    setError(null);
    try {
      const fresh = await runEvaluation(notificationId);
      setEvaluation(fresh);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to run assistant evaluation."));
    } finally {
      setRunning(false);
    }
  }

  if (loading) {
    return (
      <section className="card assistant-panel">
        <h2>Assistant</h2>
        <div>Loading...</div>
      </section>
    );
  }

  if (!evaluation) {
    return (
      <section className="card assistant-panel">
        <h2>Assistant</h2>
        <p className="muted">
          Not yet analysed. Run the assistant to evaluate this NOTSO against your uploaded
          procedures and get recommended next steps.
        </p>
        <button type="button" onClick={onRun} disabled={running}>
          {running ? "Analysing..." : "Run assistant"}
        </button>
        {error && <div className="form-error">{error}</div>}
      </section>
    );
  }

  const { structured } = evaluation;
  const actions: NextAction[] = structured.next_actions ?? [];
  const procedures = structured.applicable_procedures ?? [];
  const questions = structured.open_questions ?? [];

  return (
    <section className="card assistant-panel">
      <div className="assistant-header">
        <h2>Assistant</h2>
        <div className="assistant-meta">
          <span className="muted">
            {evaluation.model} &middot; {formatDateTime(evaluation.evaluated_at)}
          </span>
          <button type="button" onClick={onRun} disabled={running}>
            {running ? "Re-analysing..." : "Re-evaluate"}
          </button>
        </div>
      </div>

      {evaluation.error && (
        <div className="form-error">
          Assistant could not produce a structured evaluation: {evaluation.error}
        </div>
      )}

      <p className="assistant-summary">{structured.summary || evaluation.summary}</p>

      {actions.length > 0 ? (
        <>
          <h3>Next actions</h3>
          <ul className="assistant-actions">
            {actions.map((a, idx) => (
              <li key={idx}>
                <div className="action-head">
                  <span className={urgencyClass(a.urgency)}>{a.urgency}</span>
                  <strong>{a.action}</strong>
                </div>
                {a.deadline && (
                  <div className="action-deadline">By {formatDateTime(a.deadline)}</div>
                )}
                <div className="action-rationale">{a.rationale}</div>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="muted">No actions recommended. Informational only.</p>
      )}

      {procedures.length > 0 && (
        <>
          <h3>Applicable procedures</h3>
          <ul className="assistant-procedures">
            {procedures.map((p, idx) => (
              <li key={idx}>
                <strong>{p.name}</strong>
                <div className="muted">{p.reason}</div>
              </li>
            ))}
          </ul>
        </>
      )}

      {questions.length > 0 && (
        <>
          <h3>Open questions</h3>
          <ul>
            {questions.map((q, idx) => (
              <li key={idx}>{q}</li>
            ))}
          </ul>
        </>
      )}

      {error && <div className="form-error">{error}</div>}
    </section>
  );
}
