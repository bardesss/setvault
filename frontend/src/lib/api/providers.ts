import { api } from "./client";

export type ProviderKind = "musicbrainz" | "discogs" | "acoustid";

export interface ProviderConfig {
  id: string;
  provider_kind: ProviderKind;
  name: string;
  enabled: boolean;
  priority: number;
  field_priority: Record<string, string[]>;
}

export const upsertProvider = (
  kind: ProviderKind,
  body: {
    name?: string;
    enabled?: boolean;
    priority?: number;
    config?: Record<string, string>;
    field_priority?: Record<string, string[]>;
  },
) =>
  api<ProviderConfig>(`/api/admin/providers/${kind}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const testProvider = (kind: ProviderKind) =>
  api<{ ok: boolean; error?: string }>(`/api/admin/providers/${kind}/test`, {
    method: "POST",
  });
