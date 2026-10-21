import type { PageLoad } from "./$types";
import { listEntities, listDuplicates, listMerged, type EntityRow, type MergedRow } from "#lib/api/catalog_admin.ts";
import type { EntityKind } from "#lib/api/catalog.ts";

export const ssr = false;

export const load: PageLoad = async ({ url }) => {
  const kind = (url.searchParams.get("kind") as EntityKind) || "artists";
  const [items, clusters, merged] = await Promise.all([listEntities(kind), listDuplicates(kind), listMerged(kind)]);
  return { kind, items, clusters, merged } as { kind: EntityKind; items: EntityRow[]; clusters: EntityRow[][]; merged: MergedRow[] };
};
