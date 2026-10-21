import { listDiscoveries } from "#lib/api/monitors.ts";
import type { PageLoad } from "./$types";

export const ssr = false;

export const load: PageLoad = async () => {
  const discoveries = await listDiscoveries();
  return { discoveries };
};
