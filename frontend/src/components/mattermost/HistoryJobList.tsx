import type { HistoryJob } from "../../types";
import {
  formatDateTime,
  formatJobCounts,
  formatOptionalDateTime,
  isActiveJob,
  statusPillClass,
} from "../../utils/mattermostAsk";

interface Props {
  jobs: HistoryJob[];
  loading: boolean;
  canWrite: boolean;
  channelNames: Map<string, string>;
  onCancel: (job: HistoryJob) => void;
}

function channelList(ids: string[], names: Map<string, string>, empty: string): string {
  if (ids.length === 0) return empty;
  return ids.map((id) => names.get(id) ?? id).join(", ");
}

function JobRow({
  job,
  canWrite,
  channelNames,
  onCancel,
}: Omit<Props, "jobs" | "loading"> & { job: HistoryJob }) {
  return (
    <tr>
      <td>
        <span className={statusPillClass(job.status)}>{job.status}</span>
      </td>
      <td>{channelList(job.channel_ids, channelNames, "All channels")}</td>
      <td>{formatDateTime(job.run_after)}</td>
      <td>
        <div>Started {formatOptionalDateTime(job.started_at)}</div>
        <div>Finished {formatOptionalDateTime(job.finished_at)}</div>
      </td>
      <td>{formatJobCounts(job.counts)}</td>
      <td>
        {job.failed_channel_ids.length > 0 && (
          <div>Failed: {channelList(job.failed_channel_ids, channelNames, "")}</div>
        )}
        {job.error && <div className="ask-error-text">{job.error}</div>}
      </td>
      <td>
        {canWrite && isActiveJob(job) && (
          <button type="button" onClick={() => onCancel(job)}>
            Cancel
          </button>
        )}
      </td>
    </tr>
  );
}

export default function HistoryJobList({ jobs, loading, canWrite, channelNames, onCancel }: Props) {
  return (
    <table className="elsets-table">
      <thead>
        <tr>
          <th>Status</th>
          <th>Channels</th>
          <th>Run after (UTC)</th>
          <th>Started / finished (UTC)</th>
          <th>Counts</th>
          <th>Problems</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((job) => (
          <JobRow
            key={job.id}
            job={job}
            canWrite={canWrite}
            channelNames={channelNames}
            onCancel={onCancel}
          />
        ))}
        {!loading && jobs.length === 0 && (
          <tr>
            <td colSpan={7}>No full history pulls yet.</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
