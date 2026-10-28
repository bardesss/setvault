import { error } from "@sveltejs/kit";
import { get } from "svelte/store";
import { _ } from "svelte-i18n";
import { setupI18n } from "#lib/i18n/index.ts";
import type { PageLoad } from "./$types";

export interface ConnectorRow {
  id: string;
  kind: string;
  name: string;
  enabled: boolean;
  scope_filter: Record<string, unknown>;
}

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/connectors");
  if (!response.ok) {
    await setupI18n();
    throw error(response.status, get(_)("admin.connectors.load_failed"));
  }
  const body = (await response.json()) as { items: ConnectorRow[] };
  return { connectors: body.items };
};
