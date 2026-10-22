import { describe, expect, it } from "vitest";
import { fmtLocalDateTime, searchRefusal, wantedResult } from "./wanted";

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

  it("wantedResult ignores events older than last search (60 s slack)", () => {
    const at = "2026-10-18T10:00:00+00:00"; // the event's time
    const old = ev("rejected", "different audio");
    // A later search that found nothing writes no event: the old one is stale.
    expect(wantedResult(old, "2026-10-19T10:00:00+00:00")).toBe("No better copy found");
    expect(wantedResult(old, "2026-10-18T10:01:01+00:00")).toBe("No better copy found");
    // The search that wrote the event stamps the set a little later.
    expect(wantedResult(old, "2026-10-18T10:01:00+00:00")).toBe("Rejected: different audio");
    expect(wantedResult(old, at)).toBe("Rejected: different audio");
    expect(wantedResult(old, "2026-10-18T09:00:00+00:00")).toBe("Rejected: different audio");
    expect(wantedResult(ev("upgraded"), null)).toBe("Upgraded");
  });

  it("never shows a raw enum", () => {
    expect(wantedResult(ev("rejected", "something new"), null)).toBe("Rejected: something new");
    expect(wantedResult(ev("rejected"), null)).toBe("Rejected");
    expect(wantedResult(ev("merged"), null)).toBe("Merged");
  });
});

describe("searchRefusal", () => {
  it("explains a refused search for that set, capitalised", () => {
    expect(searchRefusal("not fingerprinted yet")).toBe(
      "Not fingerprinted yet — run the backfill on the Quality tab",
    );
    expect(searchRefusal("quality not measured yet")).toBe(
      "Quality not measured yet — run the backfill on the Quality tab",
    );
    expect(searchRefusal("upgrades are off for this set")).toBe("Upgrades are off for this set");
    expect(searchRefusal("something new")).toBe("Something new");
  });
});

describe("fmtLocalDateTime", () => {
  it("renders in the browser's time zone, not UTC", () => {
    const iso = "2026-10-18T23:30:00+00:00";
    expect(fmtLocalDateTime(iso)).toBe(
      new Date(iso).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" }),
    );
  });

  it("follows the given UI language and falls back to en", () => {
    const iso = "2026-10-18T12:00:00+00:00";
    expect(fmtLocalDateTime(iso, "nl")).toContain("okt");
    expect(fmtLocalDateTime(iso, "en")).toContain("Oct");
    expect(fmtLocalDateTime(iso, null)).toContain("Oct");
    expect(fmtLocalDateTime(iso, "")).toContain("Oct");
  });

  it("handles empty input", () => {
    expect(fmtLocalDateTime(null)).toBe("");
  });
});
