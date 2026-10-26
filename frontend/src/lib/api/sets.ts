import { api } from "./client";

export interface SetArtist {
  id: string;
  name: string;
  slug: string;
  role: string;
}

export interface SetSummary {
  id: string;
  slug: string;
  title: string;
  date: string | null;
  duration_seconds: number | null;
  set_type: string;
  status: string;
  artists: SetArtist[];
  tags: string[];
  created_at: string;
  venue: { name: string; slug: string; kind: string | null } | null;
}

export interface SetFacets {
  tags: { slug: string; name: string; count: number }[];
  years: number[];
  venue_kinds: string[];
}

export interface ListSetsParams {
  limit?: number;
  offset?: number;
  q?: string;
  tag?: string;
  year?: string | number;
  venue_kind?: string;
  sort?: string;
  /** Only sets whose tracklist has this track (a track id). */
  track?: string;
  /** A set slug to leave out; only meaningful with `track`. */
  exclude?: string;
}

export interface SetUpgradeHistoryItem {
  id: string;
  created_at: string;
  from_label: string;
  to_label: string;
  /** "upgraded", or "merged" when a duplicate set was merged into this one. */
  outcome?: string;
  /** A merge left the merged copy's tracklist with the recycled copy. */
  tracklist_kept?: boolean;
}

export interface SetDetail extends Omit<SetSummary, "venue"> {
  description: string | null;
  audio_stream_url: string;
  waveform_url: string | null;
  normalized_lufs: number | null;
  venue: { id: string; name: string; slug: string; kind?: string | null } | null;
  party: {
    id: string;
    name: string;
    slug: string;
    venue?: { id: string; name: string; slug: string } | null;
    series?: { id: string; name: string; slug: string } | null;
  } | null;
  embed_allowed: boolean;
  quality: { tier: string; label: string } | null;
  upgrades_enabled: boolean;
  /** The library-wide switch; while off, `upgrades_enabled` does nothing. */
  auto_upgrades_enabled: boolean;
  upgrade_history: SetUpgradeHistoryItem[];
  is_favorite: boolean;
}

export interface SetState {
  position_seconds: number;
  completed: boolean;
  playback_rate?: number;
}

export function setsQuery(params: ListSetsParams = {}): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export const listSets = (params: ListSetsParams = {}) =>
  api<{ items: SetSummary[]; total: number }>(`/api/sets${setsQuery(params)}`);

export const getFacets = () => api<SetFacets>("/api/sets/facets");

/** PATCH body. Omitted keys are left alone; `null` clears party, venue, date
 * and description. `artists` wins over `artist_ids`. */
export interface SetPatch {
  title?: string;
  date?: string | null;
  set_type?: string;
  party_id?: string | null;
  venue_id?: string | null;
  description?: string | null;
  artist_ids?: string[];
  artists?: { id: string; role: string }[];
  tag_names?: string[];
  upgrades_enabled?: boolean;
}

export const patchSet = (slug: string, patch: SetPatch) =>
  api<SetDetail>(`/api/sets/${slug}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const getSetState = (slug: string) =>
  api<SetState>(`/api/sets/${slug}/state`);

export const putSetState = (slug: string, state: SetState, init?: RequestInit) =>
  api<void>(`/api/sets/${slug}/state`, {
    method: "PUT",
    body: JSON.stringify(state),
    ...init,
  });
