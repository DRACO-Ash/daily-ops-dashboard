import { useCallback, useEffect, useMemo, useState } from "react";
import { cancelHistoryJob, listHistoryJobs } from "../../api/mattermost";
import type { HistoryJob } from "../../types";
import {
  apiErrorMessage,
  errorStatus,
  hasActiveJob,
  JOB_POLL_INTERVAL_MS,
} from "../../utils/mattermostAsk";
import HistoryJobList from "./HistoryJobList";
import HistoryRequestForm from "./HistoryRequestForm";
import type { ChannelsState } from "./useMattermostChannels";

interface Props {
  canWrite: boolean;
  channels: ChannelsState;
}

export default function HistoryTab({ canWrite, channels }: Props) {
  const [jobs, setJobs] = useState<HistoryJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      setJobs(await listHistoryJobs());
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err, "Failed to load history jobs."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const active = hasActiveJob(jobs);
  useEffect(() => {
    if (!active) return;
    const handle = globalThis.setInterval(() => load(true), JOB_POLL_INTERVAL_MS);
    return () => globalThis.clearInterval(handle);
  }, [active, load]);

  const channelNames = useMemo(
    () => new Map(channels.channels.map((c) => [c.id, c.display_name ?? c.name])),
    [channels.channels],
  );

  async function onCancel(job: HistoryJob) {
    setError(null);
    try {
      const updated = await cancelHistoryJob(job.id);
      setJobs((list) => list.map((j) => (j.id === updated.id ? updated : j)));
    } catch (err) {
      if (errorStatus(err) === 409) {
        setError("That job had already finished.");
      } else {
        setError(apiErrorMessage(err, "Cancel failed."));
      }
      await load(true);
    }
  }

  return (
    <>
      <HistoryRequestForm
        channels={channels.channels}
        loading={channels.loading}
        error={channels.error}
        canWrite={canWrite}
        onReloadChannels={channels.reload}
        onCreated={(job) => setJobs((list) => [job, ...list])}
      />
      <section className="card">
        <h2>Full history pulls</h2>
        {active && (
          <p className="muted">Updating every 10 seconds while a pull is scheduled or running.</p>
        )}
        <div className="ask-form-actions">
          <button type="button" onClick={() => load()}>
            Refresh
          </button>
        </div>
        {error && <div className="form-error">{error}</div>}
        {loading && <div>Loading...</div>}
        <HistoryJobList
          jobs={jobs}
          loading={loading}
          canWrite={canWrite}
          channelNames={channelNames}
          onCancel={onCancel}
        />
      </section>
    </>
  );
}
