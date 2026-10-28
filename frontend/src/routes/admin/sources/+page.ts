import { error } from "@sveltejs/kit";
import { get } from "svelte/store";
import { _ } from "svelte-i18n";
import { setupI18n } from "#lib/i18n/index.ts";
import type { SourceState } from "#lib/api/ingest_sources.ts";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/admin/ingest-sources");
  if (!response.ok) {
    await setupI18n();
    throw error(response.status, get(_)("admin.sources.load_failed"));
  }
  const body = (await response.json()) as { items: SourceState[] };
  return { sources: body.items };
};
