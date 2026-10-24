import { describe, expect, it } from "vitest";
import { fmtBytes } from "./format.ts";

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
