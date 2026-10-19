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

export interface SetDetail extends SetSummary {
  description: string | null;
  audio_stream_url: string;
  waveform_url: string | null;
  normalized_lufs: number | null;
  venue: { id: string; name: string; slug: string } | null;
  party: { id: string; name: string; slug: string } | null;
  embed_allowed: boolean;
  quality: { tier: string; label: string } | null;
  upgrades_enabled: boolean;
  /** The library-wide switch; while off, `upgrades_enabled` does nothing. */
  auto_upgrades_enabled: boolean;
  upgrade_history: SetUpgradeHistoryItem[];
}

export interface SetState {
  position_seconds: number;
  completed: boolean;
  playback_rate?: number;
}

export const listSets = () =>
  api<{ items: SetSummary[]; total: number }>("/api/sets");

export const getSet = (slug: string) => api<SetDetail>(`/api/sets/${slug}`);

export const patchSet = (slug: string, patch: Partial<SetDetail>) =>
  api<SetDetail>(`/api/sets/${slug}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

export const getSetState = (slug: string) =>
  api<SetState>(`/api/sets/${slug}/state`);

export const putSetState = (slug: string, state: SetState) =>
  api<void>(`/api/sets/${slug}/state`, {
    method: "PUT",
    body: JSON.stringify(state),
  });
