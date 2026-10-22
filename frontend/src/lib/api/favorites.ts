import { api } from "./client";
import type { SetSummary } from "./sets";

export interface FavoriteItem extends SetSummary {
  favorited_at: string;
}

export interface ListFavoritesParams {
  limit?: number;
  offset?: number;
}

export const favorite = (slug: string) =>
  api<void>(`/api/sets/${encodeURIComponent(slug)}/favorite`, { method: "PUT" });

export const unfavorite = (slug: string) =>
  api<void>(`/api/sets/${encodeURIComponent(slug)}/favorite`, { method: "DELETE" });

export const listMyFavorites = ({ limit = 50, offset = 0 }: ListFavoritesParams = {}) =>
  api<{ items: FavoriteItem[]; total: number }>(
    `/api/me/favorites?limit=${limit}&offset=${offset}`,
  );
