import { listEntities, type EntityKind, type EntityListItem, type EntitySort } from "#lib/api/catalog.ts";

export const BROWSE_PAGE = 50;
const SORTS: EntitySort[] = ["name", "sets", "recent"];

export interface BrowseData {
  items: EntityListItem[];
  total: number;
  q: string;
  sort: EntitySort;
}

/** First page of a browse list, from the URL's ?q= and ?sort=. */
export async function loadBrowse(kind: EntityKind, url: URL): Promise<BrowseData> {
  const q = url.searchParams.get("q") ?? "";
  const s = url.searchParams.get("sort") as EntitySort;
  const sort = SORTS.includes(s) ? s : "name";
  const r = await listEntities(kind, { q, sort, limit: BROWSE_PAGE, offset: 0 });
  return { items: r.items, total: r.total, q, sort };
}
