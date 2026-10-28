import { error } from "@sveltejs/kit";
import { get } from "svelte/store";
import { _ } from "svelte-i18n";
import { setupI18n } from "#lib/i18n/index.ts";
import type { PageLoad } from "./$types";
import type { MediaRoot } from "#lib/api/media_roots.ts";

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/media-roots");
  if (!response.ok) {
    await setupI18n();
    throw error(response.status, get(_)("admin.storage.load_failed"));
  }
  const body = (await response.json()) as { items: MediaRoot[] };
  return { roots: body.items };
};
