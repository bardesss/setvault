/** Admin navigation: groups of items shown in the nav rail, where an item
 *  that merges several pages lists them as sub-tabs. Labels are i18n keys. */

export interface AdminPage {
  href: string;
  label: string;
}

export interface AdminItem {
  /** Where the item links to: its first sub-page when it has several. */
  href: string;
  label: string;
  /** Pages shown as tabs inside the item; one-page items have none. */
  sub?: AdminPage[];
}

export interface AdminGroup {
  label: string;
  items: AdminItem[];
}

const page = (slug: string, label = `admin.layout.tab_${slug.replace("-", "_")}`): AdminPage => ({
  href: `/admin/${slug}`,
  label,
});

const merged = (label: string, sub: AdminPage[]): AdminItem => ({ href: sub[0].href, label, sub });

export const ADMIN_NAV: AdminGroup[] = [
  {
    label: "admin.layout.group_library",
    items: [
      page("catalog"),
      merged("admin.layout.item_inbox", [page("drafts"), page("duplicates"), page("unmatched")]),
      page("recycle"),
    ],
  },
  {
    label: "admin.layout.group_quality",
    items: [merged("admin.layout.tab_quality", [page("quality"), page("wanted")])],
  },
  {
    label: "admin.layout.group_ingest",
    items: [page("sources"), page("monitors"), page("watch-folders"), page("storage")],
  },
  {
    label: "admin.layout.group_integrations",
    items: [
      page("providers"),
      merged("admin.layout.item_notifications", [page("connectors"), page("email")]),
      page("webhooks"),
    ],
  },
  {
    label: "admin.layout.group_system",
    items: [
      page("users"),
      merged("admin.layout.tab_jobs", [page("jobs"), page("tasks")]),
      page("backups"),
      merged("admin.layout.tab_health", [
        page("health"),
        page("system", "admin.layout.sub_settings"),
      ]),
    ],
  },
];

const onPage = (pathname: string, href: string) =>
  pathname === href || pathname.startsWith(href + "/");

/** True when ``pathname`` is one of the item's pages. */
export function itemActive(item: AdminItem, pathname: string): boolean {
  return (item.sub ?? [item]).some((p) => onPage(pathname, p.href));
}

/** The item the current admin page belongs to, if any. */
export function activeAdminItem(pathname: string): AdminItem | undefined {
  for (const g of ADMIN_NAV) {
    const hit = g.items.find((i) => itemActive(i, pathname));
    if (hit) return hit;
  }
  return undefined;
}

/** True when ``pathname`` is this exact page (or below it). */
export const pageActive = (p: AdminPage, pathname: string) => onPage(pathname, p.href);
