import { error } from "@sveltejs/kit";
import type { ProviderConfig } from "#lib/api/providers.ts";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/admin/providers");
  if (!response.ok) {
    throw error(response.status, "Failed to load providers");
  }
  const body = (await response.json()) as { items: ProviderConfig[] };
  return { providers: body.items };
};
