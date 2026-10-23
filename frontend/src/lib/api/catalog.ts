import { api } from "./client";

export interface Artist {
  id: string; name: string; slug: string;
  country: string | null; bio: string | null; aliases: string[]; image_url: string | null;
}
export interface Venue {
  id: string; slug: string; name: string; kind: string;
  city_or_area: string | null; country: string | null; capacity: number | null; website: string | null;
}
export interface Series { id: string; slug: string; name: string; description: string | null; image_url: string | null; }
export interface Party {
  id: string; name: string; slug: string;
  venue: { id: string; name: string; slug: string } | null;
  series: { id: string; name: string; slug: string } | null;
  date: string | null; description: string | null;
}
export interface EntitySet {
  slug: string; title: string;
  artists: { name: string; slug: string }[];
  venue: { name: string; slug: string } | null;
  date: string | null; duration_seconds: number | null;
}

export type EntityKind = "artists" | "venues" | "parties" | "series";

export const getArtist = (slug: string) => api<Artist>(`/api/catalog/artists/${slug}`);
export const getVenue = (slug: string) => api<Venue>(`/api/catalog/venues/${slug}`);
export const getParty = (slug: string) => api<Party>(`/api/catalog/parties/${slug}`);
export const getSeries = (slug: string) => api<Series>(`/api/catalog/series/${slug}`);

export const patchArtist = (slug: string, patch: Partial<Artist>) =>
  api<Artist>(`/api/catalog/artists/${slug}`, { method: "PATCH", body: JSON.stringify(patch) });
export const patchVenue = (slug: string, patch: Partial<Venue>) =>
  api<Venue>(`/api/catalog/venues/${slug}`, { method: "PATCH", body: JSON.stringify(patch) });
export const patchSeries = (slug: string, patch: Partial<Series>) =>
  api<Series>(`/api/catalog/series/${slug}`, { method: "PATCH", body: JSON.stringify(patch) });
export const patchParty = (slug: string, patch: Record<string, unknown>) =>
  api<Party>(`/api/catalog/parties/${slug}`, { method: "PATCH", body: JSON.stringify(patch) });

export const createArtist = (name: string) =>
  api<Artist>("/api/catalog/artists", { method: "POST", body: JSON.stringify({ name }) });
/** A venue made from a picker: name only; kind is required by the API, so "other". */
export const createVenue = (name: string) =>
  api<Venue>("/api/catalog/venues", { method: "POST", body: JSON.stringify({ name, kind: "other" }) });
export const createParty = (body: { name: string; date?: string | null; venue_id?: string | null }) =>
  api<Party>("/api/catalog/parties", { method: "POST", body: JSON.stringify(body) });

export const getEntitySets = async (kind: EntityKind, slug: string): Promise<EntitySet[]> => {
  const r = await api<{ items: EntitySet[] }>(`/api/catalog/${kind}/${slug}/sets`);
  return r.items;
};
