import { listDiscoveries } from "#lib/api/monitors.ts";
import type { PageLoad } from "./$types";

export const ssr = false;

const STATUSES = ["pending_review", "ingested", "dismissed", "all"];

export const load: PageLoad = async ({ url }) => {
  const raw = url.searchParams.get("status");
  const status = raw && STATUSES.includes(raw) ? raw : "pending_review";
  const { items, pending_count } = await listDiscoveries(
    status === "all" ? undefined : status,
  );
  return { discoveries: items, pendingCount: pending_count, status };
};