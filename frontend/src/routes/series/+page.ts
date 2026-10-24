import type { PageLoad } from "./$types";
import { loadBrowse } from "#lib/entityBrowse.ts";

export const load: PageLoad = ({ url }) => loadBrowse("series", url);
