import { error } from "@sveltejs/kit";
import { get } from "svelte/store";
import { _ } from "svelte-i18n";
import { setupI18n } from "#lib/i18n/index.ts";
import type { PageLoad } from "./$types";
import type { Connector } from "#lib/api/connectors.ts";

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/connectors");
  if (!response.ok) {
    await setupI18n();
    throw error(response.status, get(_)("admin.email.load_failed"));
  }
  const body = (await response.json()) as { items: Connector[] };
  // The page manages the first SMTP connector; it is created on first save.
  return { connector: body.items.find((c) => c.kind === "smtp") ?? null };
};
