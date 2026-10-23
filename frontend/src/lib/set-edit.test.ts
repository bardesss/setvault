import { describe, expect, it } from "vitest";
import { diffPatch, formFromSet, roleOptions, type EditForm } from "./set-edit.ts";
import type { SetDetail } from "./api/sets.ts";

const base = (): EditForm => ({
  title: "Night One",
  artists: [
    { id: "a1", name: "Ann", slug: "ann", role: "main" },
    { id: "a2", name: "Bob", slug: "bob", role: "main" },
  ],
  party: { id: "p1", name: "Party", slug: "party", hint: null },
  venue: { id: "v1", name: "Club", slug: "club", hint: "Ghent" },
  date: "2024-06-01",
  set_type: "headline",
  description: "About it",
  tags: ["house", "techno"],
});

describe("diffPatch", () => {
  it("returns nothing when nothing changed", () => {
    expect(diffPatch(base(), base())).toEqual({});
  });

  it("sends null for a cleared venue", () => {
    expect(diffPatch(base(), { ...base(), venue: null })).toEqual({ venue_id: null });
  });

  it("sends null for a cleared party and date", () => {
    expect(diffPatch(base(), { ...base(), party: null, date: null })).toEqual({
      party_id: null,
      date: null,
    });
  });

  it("sends the new id for a changed party", () => {
    const party = { id: "p2", name: "Other", slug: "other", hint: null };
    expect(diffPatch(base(), { ...base(), party })).toEqual({ party_id: "p2" });
  });

  it("sends all artists with roles when only a role changed", () => {
    const cur = base();
    cur.artists = [cur.artists[0], { ...cur.artists[1], role: "b2b" }];
    expect(diffPatch(base(), cur)).toEqual({
      artists: [
        { id: "a1", role: "main" },
        { id: "a2", role: "b2b" },
      ],
    });
  });

  it("sends the artists in their new order when only the order changed", () => {
    const cur = base();
    cur.artists = [cur.artists[1], cur.artists[0]];
    expect(diffPatch(base(), cur)).toEqual({
      artists: [
        { id: "a2", role: "main" },
        { id: "a1", role: "main" },
      ],
    });
  });

  it("sends null for an emptied description", () => {
    expect(diffPatch(base(), { ...base(), description: "" })).toEqual({ description: null });
  });

  it("treats a whitespace description as no description", () => {
    const orig = { ...base(), description: null };
    expect(diffPatch(orig, { ...orig, description: "  " })).toEqual({});
  });

  it("sends tags as tag_names", () => {
    expect(diffPatch(base(), { ...base(), tags: ["house"] })).toEqual({ tag_names: ["house"] });
  });

  it("sends a trimmed title and set type when changed", () => {
    expect(diffPatch(base(), { ...base(), title: " Night Two ", set_type: "closer" })).toEqual({
      title: "Night Two",
      set_type: "closer",
    });
  });

  it("ignores whitespace-only title changes", () => {
    expect(diffPatch(base(), { ...base(), title: "Night One  " })).toEqual({});
  });

  it("sends null for an emptied date input", () => {
    expect(diffPatch(base(), { ...base(), date: "" })).toEqual({ date: null });
  });
});

describe("formFromSet", () => {
  it("maps the set detail onto the form", () => {
    const set = {
      title: "T",
      artists: [{ id: "a1", name: "Ann", slug: "ann", role: "b2b" }],
      party: { id: "p1", name: "P", slug: "p", venue: null, series: null },
      venue: { id: "v1", name: "V", slug: "v" },
      date: null,
      set_type: "unknown",
      description: null,
      tags: ["x"],
    } as unknown as SetDetail;
    expect(formFromSet(set)).toEqual({
      title: "T",
      artists: [{ id: "a1", name: "Ann", slug: "ann", role: "b2b", hint: null }],
      party: { id: "p1", name: "P", slug: "p", hint: null },
      venue: { id: "v1", name: "V", slug: "v", hint: null },
      date: null,
      set_type: "unknown",
      description: null,
      tags: ["x"],
    });
  });
});

describe("roleOptions", () => {
  it("offers main and b2b", () => {
    expect(roleOptions("main")).toEqual(["main", "b2b"]);
  });

  it("keeps any other existing role as an extra option", () => {
    expect(roleOptions("vs")).toEqual(["main", "b2b", "vs"]);
  });
});
