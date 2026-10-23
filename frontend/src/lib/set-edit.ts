import type { LookupRow } from "./api/lookup.ts";
import type { SetDetail, SetPatch } from "./api/sets.ts";

/** An artist chip in the editor: a lookup row that also carries its role. */
export interface EditArtist {
  id: string;
  name: string;
  slug: string;
  role: string;
  hint?: string | null;
}

export interface EditForm {
  title: string;
  artists: EditArtist[];
  party: LookupRow | null;
  venue: LookupRow | null;
  date: string | null;
  set_type: string;
  description: string | null;
  tags: string[];
}

export const SET_TYPES = ["unknown", "opener", "warmup", "headline", "closer", "b2b"] as const;

const BASE_ROLES = ["main", "b2b"];

/** The role choices for one artist chip: main, b2b, plus its own role if it is another one. */
export function roleOptions(current: string): string[] {
  return BASE_ROLES.includes(current) ? [...BASE_ROLES] : [...BASE_ROLES, current];
}

const row = (e: { id: string; name: string; slug: string }): LookupRow => ({
  id: e.id,
  name: e.name,
  slug: e.slug,
  hint: null,
});

export function formFromSet(set: SetDetail): EditForm {
  return {
    title: set.title,
    artists: set.artists.map((a) => ({ id: a.id, name: a.name, slug: a.slug, role: a.role, hint: null })),
    party: set.party ? row(set.party) : null,
    venue: set.venue ? row(set.venue) : null,
    date: set.date,
    set_type: set.set_type,
    description: set.description,
    tags: [...set.tags],
  };
}

/** Blank strings mean "no value". */
const orNull = (s: string | null): string | null => (s && s.trim() ? s : null);

const sameList = <T>(a: T[], b: T[], eq: (x: T, y: T) => boolean): boolean =>
  a.length === b.length && a.every((x, i) => eq(x, b[i]));

/** The PATCH body for the fields that differ between `original` and `current`. */
export function diffPatch(original: EditForm, current: EditForm): SetPatch {
  const patch: SetPatch = {};
  const title = current.title.trim();
  if (title !== original.title.trim()) patch.title = title;
  if (!sameList(original.artists, current.artists, (a, b) => a.id === b.id && a.role === b.role)) {
    patch.artists = current.artists.map((a) => ({ id: a.id, role: a.role }));
  }
  if ((original.party?.id ?? null) !== (current.party?.id ?? null)) {
    patch.party_id = current.party?.id ?? null;
  }
  if ((original.venue?.id ?? null) !== (current.venue?.id ?? null)) {
    patch.venue_id = current.venue?.id ?? null;
  }
  const date = orNull(current.date);
  if (orNull(original.date) !== date) patch.date = date;
  if (original.set_type !== current.set_type) patch.set_type = current.set_type;
  const description = orNull(current.description);
  if (orNull(original.description) !== description) patch.description = description;
  if (!sameList(original.tags, current.tags, (a, b) => a === b)) patch.tag_names = [...current.tags];
  return patch;
}
