// Pure helpers for the Mattermost asks and full-history views. No React, no
// DOM and no network here, so everything in this file is unit tested.

import type {
  AskCreate,
  AskExtractSource,
  AskScope,
  AskSpec,
  HistoryJob,
  UserRole,
} from "../types";

export const MIN_REFRESH_MINUTES = 15;
export const MAX_REFRESH_MINUTES = 10080;
export const MAX_LIST_ENTRIES = 20;
export const MAX_ENTRY_LENGTH = 100;
export const MAX_PATTERN_LENGTH = 200;

export const SCOPE_OPTIONS: ReadonlyArray<{ value: AskScope; label: string }> = [
  { value: "posts", label: "Every matching post" },
  { value: "thread_starts", label: "Thread starts" },
  { value: "first_per_thread", label: "First match in each thread" },
];

/** The ask form as the user edits it: lists are raw text, numbers are strings. */
export interface AskFormState {
  name: string;
  question: string;
  terms: string;
  anyTerms: string;
  authors: string;
  channels: string;
  after: string;
  before: string;
  includeArchived: boolean;
  scope: AskScope;
  extractPattern: string;
  extractSource: AskExtractSource;
  refreshMinutes: string;
}

export function emptyAskForm(): AskFormState {
  return {
    name: "",
    question: "",
    terms: "",
    anyTerms: "",
    authors: "",
    channels: "",
    after: "",
    before: "",
    includeArchived: true,
    scope: "posts",
    extractPattern: "",
    extractSource: "message",
    refreshMinutes: "",
  };
}

// Lists -------------------------------------------------------------------------

/** Split comma or newline separated text into trimmed, non-empty, unique entries. */
export function parseList(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/[,\n]/)) {
    const value = raw.trim();
    if (value !== "" && !seen.has(value)) {
      seen.add(value);
      out.push(value);
    }
  }
  return out;
}

/** One entry per line, so an entry is never confused with a separator. */
export function formatList(values: ReadonlyArray<string>): string {
  return values.join("\n");
}

/** Add one entry to list text, if it is not already there. */
export function appendToList(text: string, value: string): string {
  const trimmed = value.trim();
  const current = parseList(text);
  if (trimmed === "" || current.includes(trimmed)) return formatList(current);
  return formatList([...current, trimmed]);
}

// Spec <-> form -----------------------------------------------------------------

interface AskLike {
  name: string;
  question: string | null;
  spec: AskSpec;
  refresh_minutes: number | null;
}

export function askToForm(ask: AskLike): AskFormState {
  const { spec } = ask;
  return {
    name: ask.name,
    question: ask.question ?? "",
    terms: formatList(spec.terms),
    anyTerms: formatList(spec.any_terms),
    authors: formatList(spec.authors),
    channels: formatList(spec.channels),
    after: spec.after ?? "",
    before: spec.before ?? "",
    includeArchived: spec.include_archived,
    scope: spec.scope,
    extractPattern: spec.extract?.pattern ?? "",
    extractSource: spec.extract?.source ?? "message",
    refreshMinutes: ask.refresh_minutes === null ? "" : String(ask.refresh_minutes),
  };
}

/** Put a suggestion into the form, keeping the question the user typed. */
export function applySuggestion(
  form: AskFormState,
  suggestion: { name: string; spec: AskSpec },
): AskFormState {
  const next = askToForm({
    name: suggestion.name,
    question: form.question,
    spec: suggestion.spec,
    refresh_minutes: null,
  });
  return { ...next, refreshMinutes: form.refreshMinutes };
}

function listErrors(label: string, values: string[]): string[] {
  const errors: string[] = [];
  if (values.length > MAX_LIST_ENTRIES) {
    errors.push(`${label}: at most ${MAX_LIST_ENTRIES} entries.`);
  }
  if (values.some((v) => v.length > MAX_ENTRY_LENGTH)) {
    errors.push(`${label}: each entry must be ${MAX_ENTRY_LENGTH} characters or fewer.`);
  }
  return errors;
}

function parseRefresh(text: string): { value: number | null; error: string | null } {
  const trimmed = text.trim();
  if (trimmed === "") return { value: null, error: null };
  const value = Number(trimmed);
  if (!Number.isInteger(value) || value < MIN_REFRESH_MINUTES || value > MAX_REFRESH_MINUTES) {
    return {
      value: null,
      error: `Refresh interval must be a whole number of minutes from ${MIN_REFRESH_MINUTES} to ${MAX_REFRESH_MINUTES}, or empty.`,
    };
  }
  return { value, error: null };
}

function buildExtract(form: AskFormState): AskSpec["extract"] {
  const pattern = form.extractPattern.trim();
  if (pattern === "") return null;
  return { pattern, source: form.extractSource };
}

function extractErrors(extract: AskSpec["extract"]): string[] {
  if (!extract) return [];
  if (extract.pattern.length > MAX_PATTERN_LENGTH) {
    return [`Extract pattern must be ${MAX_PATTERN_LENGTH} characters or fewer.`];
  }
  try {
    new RegExp(extract.pattern);
  } catch {
    return ["Extract pattern is not a valid regular expression."];
  }
  return [];
}

function specErrors(spec: AskSpec): string[] {
  const errors = [
    ...listErrors("Terms", spec.terms),
    ...listErrors("Any of these terms", spec.any_terms),
    ...listErrors("Authors", spec.authors),
    ...listErrors("Channels", spec.channels),
    ...extractErrors(spec.extract),
  ];
  const narrowed =
    spec.terms.length + spec.any_terms.length + spec.authors.length + spec.channels.length > 0;
  if (!narrowed) {
    errors.push("Give at least one of terms, any of these terms, authors or channels.");
  }
  if (spec.after && spec.before && spec.after > spec.before) {
    errors.push("The 'after' date must be on or before the 'before' date.");
  }
  return errors;
}

export interface FormResult {
  payload: AskCreate | null;
  errors: string[];
}

/** Convert the form to an API payload, or explain why it cannot be saved. */
export function formToPayload(form: AskFormState): FormResult {
  const spec: AskSpec = {
    terms: parseList(form.terms),
    any_terms: parseList(form.anyTerms),
    authors: parseList(form.authors).map((a) => a.replace(/^@/, "")),
    channels: parseList(form.channels),
    after: form.after || null,
    before: form.before || null,
    include_archived: form.includeArchived,
    scope: form.scope,
    extract: buildExtract(form),
  };
  const refresh = parseRefresh(form.refreshMinutes);
  const errors: string[] = [];
  const name = form.name.trim();
  if (name === "") errors.push("Name is required.");
  errors.push(...specErrors(spec));
  if (refresh.error) errors.push(refresh.error);
  if (errors.length > 0) return { payload: null, errors };
  const question = form.question.trim();
  return {
    payload: { name, question: question || null, spec, refresh_minutes: refresh.value },
    errors: [],
  };
}

// Times -------------------------------------------------------------------------

const LOCAL_INPUT = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** Minutes east of UTC as "+hh:mm" or "-hh:mm". */
export function formatOffset(offsetMinutes: number): string {
  const sign = offsetMinutes < 0 ? "-" : "+";
  const abs = Math.abs(offsetMinutes);
  return `${sign}${pad2(Math.floor(abs / 60))}:${pad2(abs % 60)}`;
}

/**
 * Turn a datetime-local value ("2026-09-28T14:30") into ISO 8601 with the
 * offset in force at that wall time, e.g. "2026-09-28T14:30:00+01:00".
 * Pass `offsetMinutes` (east of UTC) to override the browser's zone.
 * Returns null for an empty or malformed value.
 */
export function localInputToIso(value: string, offsetMinutes?: number): string | null {
  const match = LOCAL_INPUT.exec(value.trim());
  if (!match) return null;
  const [, y, mo, d, h, mi, s] = match;
  const local = new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi));
  if (Number.isNaN(local.getTime())) return null;
  const offset = offsetMinutes ?? -local.getTimezoneOffset();
  return `${y}-${mo}-${d}T${h}:${mi}:${s ?? "00"}${formatOffset(offset)}`;
}

/** UTC "YYYY-MM-DD HH:MM:SS", matching the rest of the dashboard. */
export function formatDateTime(value: string): string {
  return new Date(value).toISOString().replace("T", " ").slice(0, 19);
}

export function formatOptionalDateTime(value: string | null, empty = "-"): string {
  if (!value) return empty;
  return formatDateTime(value);
}

export function formatRefresh(minutes: number | null): string {
  if (minutes === null) return "Only when asked";
  if (minutes % 1440 === 0) return `Every ${minutes / 1440} d`;
  if (minutes % 60 === 0) return `Every ${minutes / 60} h`;
  return `Every ${minutes} min`;
}

export function scopeLabel(scope: AskScope): string {
  return SCOPE_OPTIONS.find((o) => o.value === scope)?.label ?? scope;
}

// Errors ------------------------------------------------------------------------

interface ValidationItem {
  loc?: unknown;
  msg?: unknown;
}

function formatValidationItem(item: unknown): string {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return String(item);
  const { loc, msg } = item as ValidationItem;
  const text = typeof msg === "string" ? msg : "Invalid value";
  if (!Array.isArray(loc)) return text;
  const path = loc.filter((part) => part !== "body").join(".");
  return path === "" ? text : `${path}: ${text}`;
}

/** FastAPI's `detail`, which is a string or a list of {loc, msg}, as lines. */
export function formatErrorDetail(detail: unknown): string[] {
  if (typeof detail === "string") return [detail];
  if (Array.isArray(detail)) return detail.map(formatValidationItem);
  return [];
}

interface ErrorLike {
  message?: unknown;
  response?: { status?: number; data?: { detail?: unknown } };
}

/** Readable lines for an axios (or any) error. */
export function apiErrorLines(err: unknown, fallback: string): string[] {
  if (!err || typeof err !== "object") return [fallback];
  const { response, message } = err as ErrorLike;
  const lines = formatErrorDetail(response?.data?.detail);
  if (lines.length > 0) return lines;
  if (response?.status === 403) return ["Only operators and admins can do this."];
  if (typeof message === "string" && message !== "") return [message];
  return [fallback];
}

export function apiErrorMessage(err: unknown, fallback: string): string {
  return apiErrorLines(err, fallback).join(" ");
}

export function errorStatus(err: unknown): number | undefined {
  if (!err || typeof err !== "object") return undefined;
  return (err as ErrorLike).response?.status;
}

// Files -------------------------------------------------------------------------

/** Mirror of the server's naming: non-alphanumerics become "_", 60 chars max. */
export function csvFilename(askName: string): string {
  const safe = Array.from(askName)
    .map((c) => (/[\p{L}\p{N}]/u.test(c) ? c : "_"))
    .join("")
    .slice(0, 60);
  return `${safe || "ask"}.csv`;
}

/** Prefer the server's Content-Disposition filename, else derive one. */
export function downloadFilename(disposition: string | null, askName: string): string {
  const match = disposition ? /filename="?([^";]+)"?/i.exec(disposition) : null;
  return match ? match[1] : csvFilename(askName);
}

// Roles and polling ---------------------------------------------------------------

export function canWrite(role: UserRole | undefined | null): boolean {
  return role === "operator" || role === "admin";
}

export const ASK_POLL_INTERVAL_MS = 5000;
export const ASK_POLL_LIMIT_MS = 3 * 60 * 1000;
export const JOB_POLL_INTERVAL_MS = 10000;

/** Keep polling an ask while it is queued, for at most three minutes. */
export function shouldKeepPollingAsk(
  status: string | null,
  startedAtMs: number,
  nowMs: number,
): boolean {
  if (status !== "queued") return false;
  return nowMs - startedAtMs < ASK_POLL_LIMIT_MS;
}

export function isActiveJob(job: Pick<HistoryJob, "status">): boolean {
  return job.status === "scheduled" || job.status === "running";
}

export function hasActiveJob(jobs: ReadonlyArray<Pick<HistoryJob, "status">>): boolean {
  return jobs.some(isActiveJob);
}

export const JOB_COUNT_KEYS = ["pulled", "inserted", "updated", "deleted", "skipped"] as const;

export function formatJobCounts(counts: Record<string, number>): string {
  return JOB_COUNT_KEYS.map((key) => `${key} ${counts[key] ?? 0}`).join(", ");
}

const STATUS_PILL: Record<string, string> = {
  ok: "urgency-pill urgency-low",
  done: "urgency-pill urgency-low",
  partial: "urgency-pill urgency-medium",
  running: "urgency-pill urgency-medium",
  failed: "urgency-pill urgency-high",
  queued: "urgency-pill urgency-pending",
  scheduled: "urgency-pill urgency-pending",
};

/** Pill classes for an ask or history-job status, reusing the urgency colours. */
export function statusPillClass(status: string | null): string {
  if (!status) return "urgency-pill";
  return STATUS_PILL[status] ?? "urgency-pill";
}
