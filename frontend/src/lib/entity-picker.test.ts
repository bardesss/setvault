import { describe, expect, it } from "vitest";
import { moveItem, nextIndex, offerCreate } from "./entity-picker.ts";
import type { LookupRow } from "./api/lookup.ts";

const row = (id: string, name: string): LookupRow => ({
  id,
  name,
  slug: name.toLowerCase(),
  hint: null,
});

describe("nextIndex", () => {
  it("wraps in both directions", () => {
    expect(nextIndex(0, 1, 3)).toBe(1);
    expect(nextIndex(2, 1, 3)).toBe(0);
    expect(nextIndex(0, -1, 3)).toBe(2);
    expect(nextIndex(-1, 1, 3)).toBe(0);
    expect(nextIndex(-1, -1, 3)).toBe(2);
  });
  it("returns -1 for an empty list", () => {
    expect(nextIndex(0, 1, 0)).toBe(-1);
    expect(nextIndex(-1, -1, 0)).toBe(-1);
  });
});

describe("offerCreate", () => {
  it("is false for blank input", () => {
    expect(offerCreate("  ", [], [])).toBe(false);
  });
  it("is false when a result matches case-insensitively", () => {
    expect(offerCreate("daft punk", [row("1", "Daft Punk")], [])).toBe(false);
  });
  it("is false when a selected item matches", () => {
    expect(offerCreate(" DAFT PUNK ", [], [row("1", "Daft Punk")])).toBe(false);
  });
  it("is true otherwise", () => {
    expect(offerCreate("Daft", [row("1", "Daft Punk")], [])).toBe(true);
  });
});

describe("moveItem", () => {
  it("moves an item up and down without mutating", () => {
    const list = ["a", "b", "c"];
    expect(moveItem(list, 2, 1)).toEqual(["a", "c", "b"]);
    expect(moveItem(list, 0, 1)).toEqual(["b", "a", "c"]);
    expect(list).toEqual(["a", "b", "c"]);
  });
  it("ignores out-of-range moves", () => {
    expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"]);
    expect(moveItem(["a", "b"], 1, 2)).toEqual(["a", "b"]);
  });
});
