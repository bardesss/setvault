import { api } from "./client";

export type TracklistEntryStatus = "raw" | "resolved" | "acoustid_confirmed";

export interface TracklistEntry {
  id: string;
  position: number;
  start_seconds: number;
  end_seconds: number | null;
  raw_label: string;
  edit_notes: string | null;
  status: TracklistEntryStatus;
  confidence: number | null;
  track_id: string | null;
  mashup_with: string[];
}

export interface ParsedEntry {
  start_seconds: number;
  raw_label: string;
}

export interface ImportJob {
  id: string;
  kind: "paste" | "url_1001tl" | "ocr";
  status: "queued" | "running" | "succeeded" | "failed";
  parsed: ParsedEntry[];
  error: string | null;
  created_at: string;
}

const base = (slug: string) => `/api/sets/${encodeURIComponent(slug)}/tracklist`;

export async function listTracklist(slug: string): Promise<TracklistEntry[]> {
  const { entries } = await api<{ entries: TracklistEntry[] }>(base(slug));
  return entries;
}

export const createEntry = (
  slug: string,
  body: { start_seconds: number; raw_label: string; position?: number },
) =>
  api<TracklistEntry>(`${base(slug)}/entries`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const patchEntry = (
  slug: string,
  id: string,
  body: Partial<
    Pick<TracklistEntry, "start_seconds" | "end_seconds" | "raw_label" | "edit_notes">
  >,
) =>
  api<TracklistEntry>(`${base(slug)}/entries/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const deleteEntry = (slug: string, id: string) =>
  api<void>(`${base(slug)}/entries/${id}`, { method: "DELETE" });

export const timeShift = (slug: string, afterSeconds: number, deltaSeconds: number) =>
  api<{ affected_count: number }>(`${base(slug)}/time-shift`, {
    method: "POST",
    body: JSON.stringify({ after_seconds: afterSeconds, delta_seconds: deltaSeconds }),
  });

export const importTracklist = (
  slug: string,
  kind: "paste" | "url_1001tl" | "ocr",
  payload: Record<string, unknown>,
) =>
  api<ImportJob>(`${base(slug)}/import`, {
    method: "POST",
    body: JSON.stringify({ kind, payload }),
  });

export const acceptImport = (slug: string, jobId: string, acceptedIndexes: number[]) =>
  api<{ entries: TracklistEntry[] }>(`${base(slug)}/import/${jobId}/accept`, {
    method: "POST",
    body: JSON.stringify({ accepted_indexes: acceptedIndexes }),
  });
