import { api } from "./client.ts";

export type LookupKind = "artist" | "party" | "venue" | "series" | "tag";

export interface LookupRow {
  id: string;
  name: string;
  slug: string;
  hint: string | null;
}

export function lookup(
  kind: LookupKind,
  q: string,
  limit?: number,
): Promise<LookupRow[]> {
  const params = new URLSearchParams({ kind, q });
  if (limit !== undefined) params.set("limit", String(limit));
  return api<LookupRow[]>(`/api/catalog/lookup?${params.toString()}`);
}
