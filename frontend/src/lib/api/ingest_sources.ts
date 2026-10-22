import { api } from "./client";

export interface SourceCandidate {
  source_kind: string;
  external_id: string;
  title: string;
  uploader: string | null;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  webpage_url: string;
  already_in_library: boolean;
  expected_tier?: string | null;
}

export interface SourceState {
  kind: string;
  name: string;
  enabled: boolean;
  state: string;
  consecutive_failures: number;
  last_error: string | null;
  rate_limit_max: number;
  rate_limit_window_seconds: number;
}

export interface SourceSearchResult {
  items: SourceCandidate[];
  errored_sources: string[];
}

export async function searchSources(q: string): Promise<SourceSearchResult> {
  return api<SourceSearchResult>("/api/ingest-sources/search", {
    method: "POST",
    body: JSON.stringify({ q }),
  });
}

export async function listSources(): Promise<SourceState[]> {
  const { items } = await api<{ items: SourceState[] }>(
    "/api/admin/ingest-sources",
  );
  return items;
}

export const setSourceEnabled = (kind: string, enabled: boolean) =>
  api<SourceState>(`/api/admin/ingest-sources/${encodeURIComponent(kind)}`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });

export const setSourceRateLimit = (
  kind: string,
  rate_limit_max: number,
  rate_limit_window_seconds: number,
) =>
  api<SourceState>(`/api/admin/ingest-sources/${encodeURIComponent(kind)}`, {
    method: "PUT",
    body: JSON.stringify({ rate_limit_max, rate_limit_window_seconds }),
  });
