import { error } from "@sveltejs/kit";
import type { SourceState } from "#lib/api/ingest_sources.ts";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/admin/ingest-sources");
  if (!response.ok) {
    throw error(response.status, "Failed to load sources");
  }
  const body = (await response.json()) as { items: SourceState[] };
  return { sources: body.items };
};
