import { describe, expect, it } from "vitest";
import type { AskSpec } from "../types";
import {
  apiErrorLines,
  appendToList,
  applySuggestion,
  askToForm,
  canWrite,
  csvFilename,
  downloadFilename,
  emptyAskForm,
  formatErrorDetail,
  formatJobCounts,
  formatOffset,
  formatRefresh,
  formToPayload,
  hasActiveJob,
  localInputToIso,
  parseList,
  shouldKeepPollingAsk,
} from "./mattermostAsk";

const SPEC: AskSpec = {
  terms: ["COSMOS 2589"],
  any_terms: ["photometric", "brightness"],
  authors: ["jsmith"],
  channels: ["sda-ops"],
  after: "2026-01-01",
  before: "2026-02-01",
  include_archived: false,
  scope: "thread_starts",
  extract: { pattern: "ID (\\d+)", source: "thread_title" },
};

describe("parseList", () => {
  it("splits on commas and newlines, trims, drops blanks and duplicates", () => {
    expect(parseList(" a, b\n\nc ,a,, \n b")).toEqual(["a", "b", "c"]);
  });

  it("returns an empty list for blank text", () => {
    expect(parseList("  \n , ")).toEqual([]);
  });
});

describe("appendToList", () => {
  it("adds a new entry and ignores one already present", () => {
    expect(appendToList("alice", "bob")).toBe("alice\nbob");
    expect(appendToList("alice\nbob", "bob")).toBe("alice\nbob");
  });
});

describe("spec and form conversion", () => {
  it("round trips an ask through the form unchanged", () => {
    const form = askToForm({ name: "Cosmos", question: "Q", spec: SPEC, refresh_minutes: 60 });
    expect(form.terms).toBe("COSMOS 2589");
    expect(form.anyTerms).toBe("photometric\nbrightness");
    expect(form.refreshMinutes).toBe("60");
    const result = formToPayload(form);
    expect(result.errors).toEqual([]);
    expect(result.payload).toEqual({
      name: "Cosmos",
      question: "Q",
      spec: SPEC,
      refresh_minutes: 60,
    });
  });

  it("maps empty optional fields to null and strips @ from authors", () => {
    const form = { ...emptyAskForm(), name: " Mine ", authors: "@alice, bob" };
    const { payload } = formToPayload(form);
    expect(payload?.name).toBe("Mine");
    expect(payload?.question).toBeNull();
    expect(payload?.refresh_minutes).toBeNull();
    expect(payload?.spec.authors).toEqual(["alice", "bob"]);
    expect(payload?.spec.after).toBeNull();
    expect(payload?.spec.extract).toBeNull();
    expect(payload?.spec.include_archived).toBe(true);
  });

  it("rejects a form that does not narrow the pull", () => {
    const form = { ...emptyAskForm(), name: "Everything" };
    const result = formToPayload(form);
    expect(result.payload).toBeNull();
    expect(result.errors).toContain(
      "Give at least one of terms, any of these terms, authors or channels.",
    );
  });

  it("rejects a missing name, reversed dates, bad refresh and a bad pattern together", () => {
    const form = {
      ...emptyAskForm(),
      terms: "x",
      after: "2026-03-01",
      before: "2026-02-01",
      refreshMinutes: "10",
      extractPattern: "(unclosed",
    };
    const { payload, errors } = formToPayload(form);
    expect(payload).toBeNull();
    expect(errors).toHaveLength(4);
    expect(errors[0]).toBe("Name is required.");
  });

  it("accepts the refresh bounds and rejects fractions", () => {
    const base = { ...emptyAskForm(), name: "n", terms: "x" };
    expect(formToPayload({ ...base, refreshMinutes: "15" }).payload?.refresh_minutes).toBe(15);
    expect(formToPayload({ ...base, refreshMinutes: "10080" }).payload?.refresh_minutes).toBe(
      10080,
    );
    expect(formToPayload({ ...base, refreshMinutes: "10081" }).payload).toBeNull();
    expect(formToPayload({ ...base, refreshMinutes: "30.5" }).payload).toBeNull();
  });

  it("rejects more than 20 entries in a list", () => {
    const many = Array.from({ length: 21 }, (_, i) => `t${i}`).join(",");
    const { errors } = formToPayload({ ...emptyAskForm(), name: "n", terms: many });
    expect(errors).toEqual(["Terms: at most 20 entries."]);
  });

  it("applies a suggestion but keeps the question and refresh interval", () => {
    const form = { ...emptyAskForm(), question: "What about COSMOS?", refreshMinutes: "30" };
    const next = applySuggestion(form, { name: "Cosmos", spec: SPEC });
    expect(next.name).toBe("Cosmos");
    expect(next.question).toBe("What about COSMOS?");
    expect(next.refreshMinutes).toBe("30");
    expect(next.scope).toBe("thread_starts");
  });
});

describe("localInputToIso", () => {
  it("adds seconds and the given offset", () => {
    expect(localInputToIso("2026-09-28T14:30", 60)).toBe("2026-09-28T14:30:00+01:00");
    expect(localInputToIso("2026-09-28T14:30", 0)).toBe("2026-09-28T14:30:00+00:00");
    expect(localInputToIso("2026-09-28T14:30:15", -330)).toBe("2026-09-28T14:30:15-05:30");
  });

  it("uses the local zone by default and names the same instant", () => {
    const iso = localInputToIso("2026-01-15T09:05");
    expect(iso).toMatch(/^2026-01-15T09:05:00[+-]\d{2}:\d{2}$/);
    expect(Date.parse(iso ?? "")).toBe(new Date(2026, 0, 15, 9, 5).getTime());
  });

  it("returns null for empty or malformed input", () => {
    expect(localInputToIso("")).toBeNull();
    expect(localInputToIso("28/09/2026 14:30")).toBeNull();
  });

  it("formats offsets with a sign", () => {
    expect(formatOffset(330)).toBe("+05:30");
    expect(formatOffset(-600)).toBe("-10:00");
  });
});

describe("error formatting", () => {
  it("passes a string detail through", () => {
    expect(formatErrorDetail("Ask not found")).toEqual(["Ask not found"]);
  });

  it("formats FastAPI validation lists without the body prefix", () => {
    const detail = [
      { loc: ["body", "spec", "terms"], msg: "Value error, too long" },
      { loc: ["body"], msg: "Give at least one" },
    ];
    expect(formatErrorDetail(detail)).toEqual([
      "spec.terms: Value error, too long",
      "Give at least one",
    ]);
  });

  it("falls back to a permission message for a bare 403, then to the message", () => {
    expect(apiErrorLines({ response: { status: 403, data: {} } }, "x")).toEqual([
      "Only operators and admins can do this.",
    ]);
    expect(apiErrorLines({ message: "Network Error" }, "x")).toEqual(["Network Error"]);
    expect(apiErrorLines(null, "Fallback")).toEqual(["Fallback"]);
  });
});

describe("files", () => {
  it("builds a CSV filename like the server", () => {
    expect(csvFilename("COSMOS 2589 / brightness")).toBe("COSMOS_2589___brightness.csv");
    expect(csvFilename("")).toBe("ask.csv");
    expect(csvFilename("a".repeat(80))).toBe(`${"a".repeat(60)}.csv`);
  });

  it("prefers the Content-Disposition filename", () => {
    expect(downloadFilename('attachment; filename="server.csv"', "x")).toBe("server.csv");
    expect(downloadFilename(null, "My ask")).toBe("My_ask.csv");
  });
});

describe("roles, polling and jobs", () => {
  it("allows writes for operators and admins only", () => {
    expect(canWrite("operator")).toBe(true);
    expect(canWrite("admin")).toBe(true);
    expect(canWrite("analyst")).toBe(false);
    expect(canWrite(undefined)).toBe(false);
  });

  it("polls a queued ask for up to three minutes", () => {
    expect(shouldKeepPollingAsk("queued", 0, 179_000)).toBe(true);
    expect(shouldKeepPollingAsk("queued", 0, 180_000)).toBe(false);
    expect(shouldKeepPollingAsk("ok", 0, 1000)).toBe(false);
  });

  it("detects active history jobs and formats counts", () => {
    expect(hasActiveJob([{ status: "done" }, { status: "running" }])).toBe(true);
    expect(hasActiveJob([{ status: "done" }, { status: "cancelled" }])).toBe(false);
    expect(formatJobCounts({ pulled: 5, inserted: 3 })).toBe(
      "pulled 5, inserted 3, updated 0, deleted 0, skipped 0",
    );
  });

  it("describes refresh intervals", () => {
    expect(formatRefresh(null)).toBe("Only when asked");
    expect(formatRefresh(90)).toBe("Every 90 min");
    expect(formatRefresh(120)).toBe("Every 2 h");
    expect(formatRefresh(10080)).toBe("Every 7 d");
  });
});
