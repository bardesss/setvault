import { error } from "@sveltejs/kit";
import { get } from "svelte/store";
import { _ } from "svelte-i18n";
import { setupI18n } from "#lib/i18n/index.ts";
import type { ProviderConfig } from "#lib/api/providers.ts";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/admin/providers");
  if (!response.ok) {
    await setupI18n();
    throw error(response.status, get(_)("admin.providers.load_failed"));
  }
  const body = (await response.json()) as { items: ProviderConfig[] };
  return { providers: body.items };
};
