import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import type { SetDetail } from "#lib/api/sets.ts";

export const load: PageLoad = async ({ fetch, params }) => {
  const response = await fetch(`/api/sets/${params.slug}`);
  if (response.status === 404) {
    throw error(404, "Set not found");
  }
  if (!response.ok) {
    throw error(response.status, "Failed to load set");
  }
  const set: SetDetail = await response.json();
  return { set };
};
