import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import type { SetSummary } from "#lib/api/sets.ts";

export const load: PageLoad = async ({ fetch }) => {
  // Auth is enforced by the API: an unauthenticated /api/sets returns 401,
  // which propagates through the !response.ok guard below.
  const response = await fetch("/api/sets");
  if (!response.ok) {
    throw error(response.status, "Failed to load library");
  }
  const body = (await response.json()) as { items: SetSummary[] };
  return { sets: body.items };
};
