import { describe, expect, it } from "vitest";
import { fmtBytes, fmtDate, fmtDuration, fmtLocalDateTime, fmtNumber } from "./format.ts";

describe("fmtBytes", () => {
  it("shows a dash for nothing", () => {
    expect(fmtBytes(0)).toBe("—");
    expect(fmtBytes(null)).toBe("—");
    expect(fmtBytes(undefined)).toBe("—");
    expect(fmtBytes(-5)).toBe("—");
  });

  it("uses 1024-based units, one decimal below 10", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(1536)).toBe("1.5 K");
    expect(fmtBytes(10 * 1024)).toBe("10 K");
    expect(fmtBytes(3.2 * 1024 ** 4)).toBe("3.2 T");
  });

  it("whole bytes have no decimal", () => {
    expect(fmtBytes(5)).toBe("5 B");
  });

  it("rounding never shows 10.0 or 1024 of a unit", () => {
    expect(fmtBytes(9.97 * 1024)).toBe("10 K");
    expect(fmtBytes(1024 ** 2 - 1)).toBe("1.0 M");
  });

  it("stops at T", () => {
    expect(fmtBytes(2048 * 1024 ** 4)).toBe("2048 T");
  });
});

describe("fmtDuration", () => {
  it("shows h:mm:ss from an hour up", () => {
    expect(fmtDuration(4500)).toBe("1:15:00");
    expect(fmtDuration(3661)).toBe("1:01:01");
  });
  it("shows m:ss below an hour and floors fractions", () => {
    expect(fmtDuration(59.9)).toBe("0:59");
    expect(fmtDuration(65)).toBe("1:05");
    expect(fmtDuration(0)).toBe("0:00");
  });
  it("falls back to 0:00 for bad input", () => {
    expect(fmtDuration(NaN)).toBe("0:00");
    expect(fmtDuration(-3)).toBe("0:00");
    expect(fmtDuration(null)).toBe("0:00");
    expect(fmtDuration(undefined)).toBe("0:00");
  });
});

describe("locale-aware formatting", () => {
  it("fmtBytes uses the language's decimal mark", () => {
    expect(fmtBytes(1536, "en")).toBe("1.5 K");
    expect(fmtBytes(1536, "nl")).toBe("1,5 K");
    expect(fmtBytes(1536, "de")).toBe("1,5 K");
    expect(fmtBytes(2048 * 1024 ** 4, "nl")).toBe("2048 T");
  });
  it("fmtNumber groups digits per language", () => {
    expect(fmtNumber(1234567, "en")).toBe("1,234,567");
    expect(fmtNumber(1234567, "nl")).toBe("1.234.567");
  });
  it("fmtDate follows the language", () => {
    const iso = "2026-01-02T10:00:00Z";
    for (const loc of ["en", "nl", "fr"]) {
      const want = new Date(iso).toLocaleDateString(loc, { dateStyle: "medium" });
      expect(fmtDate(iso, loc)).toBe(want);
      expect(fmtDate(iso, loc)).toContain("2026");
    }
    expect(fmtDate(iso, "nl")).not.toBe(fmtDate(iso, "en"));
  });
  it("fmtDate and fmtLocalDateTime handle nothing and garbage", () => {
    expect(fmtDate("garbage", "en")).toBe("—");
    expect(fmtDate(null, "en")).toBe("—");
    expect(fmtLocalDateTime(null, "en")).toBe("");
  });
  it("fmtLocalDateTime follows the language", () => {
    const iso = "2026-01-02T10:00:00Z";
    expect(fmtLocalDateTime(iso, "nl")).toBe(
      new Date(iso).toLocaleString("nl", { dateStyle: "medium", timeStyle: "short" }),
    );
  });
});
