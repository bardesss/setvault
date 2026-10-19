import { describe, expect, it } from "vitest";
import { fmtLocalDateTime, wantedResult } from "./wanted";

const ev = (outcome: string, reason: string | null = null) => ({
  outcome, reason, created_at: "2026-10-18T10:00:00+00:00",
});

describe("wantedResult", () => {
  it("says what happened in plain English", () => {
    expect(wantedResult(ev("upgraded"), null)).toBe("Upgraded");
    expect(wantedResult(ev("rejected", "different audio"), null)).toBe("Rejected: different audio");
    expect(wantedResult(ev("rejected", "not better"), null)).toBe("Rejected: not better");
    expect(wantedResult(ev("rejected", "rip failed: RuntimeError: boom"), null)).toBe("Download failed");
    expect(wantedResult(ev("rejected", "probe failed: Video unavailable"), null)).toBe("Download failed");
    expect(wantedResult(ev("rejected", "upgrades off"), null)).toBe("Skipped: upgrades are off");
  });

  it("tells a fruitless search from no search", () => {
    expect(wantedResult(null, "2026-10-18T10:00:00+00:00")).toBe("No better copy found");
    expect(wantedResult(null, null)).toBe("None yet");
  });

  it("never shows a raw enum", () => {
    expect(wantedResult(ev("rejected", "something new"), null)).toBe("Rejected: something new");
    expect(wantedResult(ev("rejected"), null)).toBe("Rejected");
    expect(wantedResult(ev("merged"), null)).toBe("Merged");
  });
});

describe("fmtLocalDateTime", () => {
  it("renders in the browser's time zone, not UTC", () => {
    const iso = "2026-10-18T23:30:00+00:00";
    expect(fmtLocalDateTime(iso)).toBe(
      new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }),
    );
    expect(fmtLocalDateTime(null)).toBe("");
  });
});
