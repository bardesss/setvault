import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import { getArtist, getEntitySets, type Artist, type EntitySet } from "#lib/api/catalog.ts";

export const load: PageLoad = async ({ fetch, params }) => {
  void fetch; // universal load runs in the browser; api() uses window.fetch
  let artist: Artist;
  try {
    artist = await getArtist(params.slug);
  } catch {
    throw error(404, "Artist not found");
  }
  const sets: EntitySet[] = await getEntitySets("artists", params.slug);
  return { artist, sets };
};
