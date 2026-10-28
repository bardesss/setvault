import { api } from "./client";
import type { SetSummary } from "./sets";

export interface Playlist {
  id: string;
  name: string;
  description: string | null;
  item_count: number;
  total_duration_seconds: number;
  created_at: string;
  updated_at: string;
}

export interface PlaylistItem extends SetSummary {
  position: number;
  added_at: string;
}

export interface PlaylistDetail extends Playlist {
  items: PlaylistItem[];
}

export interface SetPlaylist {
  id: string;
  name: string;
  contains: boolean;
}

const base = (id: string) => `/api/me/playlists/${encodeURIComponent(id)}`;

export const listPlaylists = () => api<{ items: Playlist[] }>("/api/me/playlists");

export const createPlaylist = (name: string) =>
  api<PlaylistDetail>("/api/me/playlists", {
    method: "POST",
    body: JSON.stringify({ name }),
  });

export const getPlaylist = (id: string) => api<PlaylistDetail>(base(id));

export const renamePlaylist = (id: string, name: string) =>
  api<Playlist>(base(id), { method: "PATCH", body: JSON.stringify({ name }) });

export const deletePlaylist = (id: string) => api<void>(base(id), { method: "DELETE" });

export const reorderPlaylist = (id: string, slugs: string[]) =>
  api<PlaylistDetail>(`${base(id)}/items`, {
    method: "PUT",
    body: JSON.stringify({ slugs }),
  });

export const addPlaylistItem = (id: string, slug: string) =>
  api<void>(`${base(id)}/items`, { method: "POST", body: JSON.stringify({ slug }) });

export const removePlaylistItem = (id: string, slug: string) =>
  api<void>(`${base(id)}/items/${encodeURIComponent(slug)}`, { method: "DELETE" });

export const listSetPlaylists = (slug: string) =>
  api<{ items: SetPlaylist[] }>(`/api/sets/${encodeURIComponent(slug)}/playlists`);
