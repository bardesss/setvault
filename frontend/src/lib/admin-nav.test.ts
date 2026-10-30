import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ADMIN_NAV, activeAdminItem } from "./admin-nav.ts";

const ADMIN_ROUTES = fileURLToPath(new URL("../routes/admin/", import.meta.url));

const navPages = ADMIN_NAV.flatMap((g) => g.items.flatMap((i) => (i.sub ?? [i]).map((p) => p.href)));

describe("admin nav", () => {
  it("lists every admin page exactly once", () => {
    const routes = readdirSync(ADMIN_ROUTES)
      .filter((d) => statSync(join(ADMIN_ROUTES, d)).isDirectory())
      .map((d) => `/admin/${d}`)
      .sort();
    expect([...navPages].sort()).toEqual(routes);
  });

  it("finds the merged item for any of its pages", () => {
    expect(activeAdminItem("/admin/duplicates")?.label).toBe("admin.layout.item_inbox");
    expect(activeAdminItem("/admin/wanted")?.href).toBe("/admin/quality");
    expect(activeAdminItem("/admin/system")?.href).toBe("/admin/health");
    expect(activeAdminItem("/admin/users")?.sub).toBeUndefined();
    expect(activeAdminItem("/sets")).toBeUndefined();
  });
});
