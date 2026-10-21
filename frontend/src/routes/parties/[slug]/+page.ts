// frontend/src/routes/parties/[slug]/+page.ts
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import { getParty, getEntitySets, type Party, type EntitySet } from "#lib/api/catalog.ts";

export const load: PageLoad = async ({ params }) => {
  let party: Party;
  try { party = await getParty(params.slug); } catch { throw error(404, "Party not found"); }
  const sets: EntitySet[] = await getEntitySets("parties", params.slug);
  return { party, sets };
};
