import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import type { SetFacets, SetSummary } from "#lib/api/sets.ts";
import { setsQuery } from "#lib/api/sets.ts";

const DEFAULT_LIMIT = 50;
const EMPTY_FACETS: SetFacets = { tags: [], years: [], venue_kinds: [] };

export const load: PageLoad = async ({ fetch, url }) => {
  const p = url.searchParams;
  const parsed = Number.parseInt(p.get("limit") ?? "", 10);
  const limit =
    Number.isFinite(parsed) && parsed >= 1 ? Math.min(parsed, 200) : DEFAULT_LIMIT;
  const filters = {
    q: p.get("q") ?? "",
    tag: p.get("tag") ?? "",
    year: p.get("year") ?? "",
    venue_kind: p.get("venue_kind") ?? "",
    sort: p.get("sort") || "recent",
  };
  // Auth is enforced by the API: an unauthenticated /api/sets returns 401,
  // which propagates through the !response.ok guard below.
  const [response, facetsRes] = await Promise.all([
    fetch(`/api/sets${setsQuery({ ...filters, limit, offset: 0 })}`),
    fetch("/api/sets/facets"),
  ]);
  if (!response.ok) {
    throw error(response.status, "Failed to load library");
  }
  const body = (await response.json()) as { items: SetSummary[]; total: number };
  const facets = facetsRes.ok ? ((await facetsRes.json()) as SetFacets) : EMPTY_FACETS;
  return { sets: body.items, total: body.total, facets, limit, filters };
};
