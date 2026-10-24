import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import type { MediaRoot } from "#lib/api/media_roots.ts";

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/media-roots");
  if (!response.ok) {
    throw error(response.status, "Failed to load media roots");
  }
  const body = (await response.json()) as { items: MediaRoot[] };
  return { roots: body.items };
};
