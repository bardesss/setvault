import { describe, expect, it } from "vitest";
import { isBadTrackFilter, isTrackId } from "./trackFilter.ts";

describe("trackFilter", () => {
  it("recognises a uuid", () => {
    expect(isTrackId("3f2b8c1e-5a4d-4e6f-9a1b-0c2d3e4f5a6b")).toBe(true);
    expect(isTrackId("not-a-uuid")).toBe(false);
    expect(isTrackId("")).toBe(false);
  });

  it("treats only a 422 with a track set as a bad filter", () => {
    expect(isBadTrackFilter(422, "x")).toBe(true);
    expect(isBadTrackFilter(422, "")).toBe(false);
    expect(isBadTrackFilter(500, "x")).toBe(false);
  });
});
