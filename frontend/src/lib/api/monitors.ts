import { api } from "./client";

export interface Monitor {
  id: string;
  kind: "query" | "entity";
  query_text: string | null;
  source_kind: string | null;
  external_id: string | null;
  enabled: boolean;
  per_poll_cap: number;
  last_checked_at: string | null;
  created_at: string;
  catalog_kind: "artist" | "party" | "venue" | null;
  catalog_id: string | null;
  catalog_name: string | null;
  catalog_slug: string | null;
}

export interface Discovery {
  id: string;
  monitor_id: string;
  source_kind: string;
  external_id: string;
  title: string;
  uploader: string | null;
  webpage_url: string;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  confidence: "high" | "low";
  status: "auto_ingested" | "pending_review" | "ingested" | "dismissed";
  created_at: string;
}

export async function listMonitors(): Promise<Monitor[]> {
  const { items } = await api<{ items: Monitor[] }>("/api/monitors");
  return items;
}

export function createMonitor(body: {
  kind: "query" | "entity";
  query_text?: string;
  source_kind?: string | null;
  external_id?: string | null;
  per_poll_cap?: number;
  catalog_kind?: "artist" | "party" | "venue";
  catalog_id?: string;
}): Promise<Monitor> {
  return api<Monitor>("/api/monitors", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function setMonitorEnabled(
  id: string,
  enabled: boolean,
): Promise<Monitor> {
  return api<Monitor>(`/api/monitors/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

export function updateMonitor(
  id: string,
  patch: {
    enabled?: boolean;
    query_text?: string;
    source_kind?: string | null;
    per_poll_cap?: number;
  },
): Promise<Monitor> {
  return api<Monitor>(`/api/monitors/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

export async function deleteMonitor(id: string): Promise<void> {
  await api<void>(`/api/monitors/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function listDiscoveries(
  status?: string,
): Promise<{ items: Discovery[]; pending_count: number }> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return api<{ items: Discovery[]; pending_count: number }>(
    `/api/me/discoveries${qs}`,
  );
}

export async function ripDiscovery(id: string): Promise<void> {
  await api<void>(`/api/me/discoveries/${encodeURIComponent(id)}/rip`, {
    method: "POST",
  });
}

export async function dismissDiscovery(id: string): Promise<void> {
  await api<void>(`/api/me/discoveries/${encodeURIComponent(id)}/dismiss`, {
    method: "POST",
  });
}
