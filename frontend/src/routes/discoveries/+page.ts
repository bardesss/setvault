import { listDiscoveries } from "#lib/api/monitors.ts";
import type { PageLoad } from "./$types";

export const ssr = false;

const FILTERS: Record<string, string[] | undefined> = {
  pending_review: ["pending_review"],
  ingested: ["ingested", "auto_ingested"],
  dismissed: ["dismissed"],
  all: undefined,
};

export const load: PageLoad = async ({ url }) => {
  const raw = url.searchParams.get("status");
  const status = raw && raw in FILTERS ? raw : "pending_review";
  const { items, pending_count } = await listDiscoveries(FILTERS[status]);
  return { discoveries: items, pendingCount: pending_count, status };
};
