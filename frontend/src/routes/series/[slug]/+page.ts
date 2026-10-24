// frontend/src/routes/series/[slug]/+page.ts
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import { getSeries, getEntitySets, type Series } from "#lib/api/catalog.ts";

export const load: PageLoad = async ({ params }) => {
  let series: Series;
  try { series = await getSeries(params.slug); } catch { throw error(404, "Series not found"); }
  const page = await getEntitySets("series", params.slug);
  return { series, sets: page.items, setsTotal: page.total };
};
