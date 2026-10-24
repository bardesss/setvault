import { api } from "./client";

export type RootHealth = "ok" | "unreachable" | "readonly" | "near_full" | "unknown";

export interface MediaRoot {
  id: string;
  name: string;
  host_path: string;
  enabled: boolean;
  default_for_ingest: boolean;
  max_bytes: number | null;
  naming_template: string | null;
  last_health_status: RootHealth | null;
  set_count: number;
}

export interface MediaRootCreate {
  name: string;
  host_path: string;
  default_for_ingest: boolean;
  max_bytes: number | null;
  naming_template: string | null;
}

/** Partial edit; an explicit null clears max_bytes / naming_template. */
export type MediaRootPatch = Partial<
  Pick<MediaRoot, "name" | "enabled" | "default_for_ingest" | "max_bytes" | "naming_template">
>;

export interface NamingPreview {
  errors: string[];
  warn_no_unique_token: boolean;
  samples: string[];
}

export async function listMediaRoots(): Promise<MediaRoot[]> {
  return (await api<{ items: MediaRoot[] }>("/api/media-roots")).items;
}

export function createMediaRoot(body: MediaRootCreate): Promise<MediaRoot> {
  return api<MediaRoot>("/api/media-roots", { method: "POST", body: JSON.stringify(body) });
}

export function patchMediaRoot(id: string, body: MediaRootPatch): Promise<MediaRoot> {
  return api<MediaRoot>(`/api/media-roots/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function probeMediaRoot(id: string): Promise<MediaRoot> {
  return api<MediaRoot>(`/api/media-roots/${id}/probe`, { method: "POST" });
}

export function reapplyTemplate(id: string): Promise<void> {
  return api<void>(`/api/media-roots/${id}/reapply-template`, { method: "POST" });
}

export function deleteMediaRoot(id: string): Promise<void> {
  return api<void>(`/api/media-roots/${id}`, { method: "DELETE" });
}

export function previewNaming(template: string): Promise<NamingPreview> {
  return api<NamingPreview>("/api/media-roots/naming-preview", {
    method: "POST",
    body: JSON.stringify({ template }),
  });
}
