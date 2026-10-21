// frontend/src/routes/venues/[slug]/+page.ts
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import { getVenue, getEntitySets, type Venue, type EntitySet } from "#lib/api/catalog.ts";

export const load: PageLoad = async ({ params }) => {
  let venue: Venue;
  try { venue = await getVenue(params.slug); } catch { throw error(404, "Venue not found"); }
  const sets: EntitySet[] = await getEntitySets("venues", params.slug);
  return { venue, sets };
};
