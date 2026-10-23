import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import type { Connector } from "#lib/api/connectors.ts";

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/connectors");
  if (!response.ok) {
    throw error(response.status, "Failed to load email settings");
  }
  const body = (await response.json()) as { items: Connector[] };
  // The page manages the first SMTP connector; it is created on first save.
  return { connector: body.items.find((c) => c.kind === "smtp") ?? null };
};
