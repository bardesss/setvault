import { describe, expect, it } from "vitest";
import { setsQuery } from "./sets.ts";

describe("setsQuery", () => {
  it("includes the track filter", () => {
    expect(setsQuery({ track: "x" })).toBe("?track=x");
  });

  it("omits track when undefined or empty", () => {
    expect(setsQuery({ track: undefined, q: "a" })).toBe("?q=a");
    expect(setsQuery({ track: "" })).toBe("");
  });
});
