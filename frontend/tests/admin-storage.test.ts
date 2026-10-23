import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// SW caches /api GETs; block so the lists below are always fresh.
test.use({ serviceWorkers: "block" });

interface RootRow {
  id: string;
  name: string;
  host_path: string;
}

async function csrf(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name === "csrf_token")?.value ?? "";
}

async function roots(page: Page): Promise<RootRow[]> {
  return ((await (await page.request.get("/api/media-roots")).json()) as { items: RootRow[] }).items;
}

test("storage tab: add a root with a template preview, edit, check, re-apply dialog, delete", async ({
  page,
  request,
}) => {
  await loginAs(page, request);

  // A real folder under the seeded e2e media root; this test owns it.
  const seed = (await roots(page)).find((r) => r.name === "e2e-seed");
  if (!seed) throw new Error("e2e seed media root is missing");
  const suffix = `${Date.now()}-${test.info().workerIndex}`;
  const dir = path.join(seed.host_path, `t13-${suffix}`);
  fs.mkdirSync(dir, { recursive: true });
  const name = `t13-root-${suffix}`;
  const renamed = `${name}-renamed`;

  try {
    await page.goto("/admin/storage");
    // The first hit of a route compiles it on the dev server.
    await expect(page.getByRole("heading", { name: "Storage" })).toBeVisible({ timeout: 20_000 });

    // Add: the template field shows a live preview before saving.
    await page.getByRole("button", { name: "Add media root" }).click();
    const dialog = page.getByRole("dialog", { name: "Add media root" });
    await dialog.getByLabel("Name", { exact: true }).fill(name);
    await dialog.getByLabel("Host path").fill(dir);
    await dialog.getByLabel("Naming template").fill("{Artist}/{Slug}.{Ext}");
    await expect(dialog.getByTestId("naming-sample").first()).toBeVisible();
    await expect(dialog.getByTestId("naming-warn")).toHaveCount(0);

    // A template without a unique token warns; an unknown token is an error.
    await dialog.getByLabel("Naming template").fill("{Artist}.{Ext}");
    await expect(dialog.getByTestId("naming-warn")).toBeVisible();
    await dialog.getByLabel("Naming template").fill("{Nope}/{Slug}.{Ext}");
    await expect(dialog.getByTestId("naming-error").first()).toBeVisible();
    await dialog.getByLabel("Naming template").fill("{Artist}/{Slug}.{Ext}");
    await expect(dialog.getByTestId("naming-sample").first()).toBeVisible();

    await dialog.getByRole("button", { name: "Save" }).click();
    const row = page.getByTestId("root-row").filter({ hasText: name });
    await expect(row).toBeVisible();
    await expect(row.getByTestId("root-health")).not.toBeEmpty();

    // Edit: rename; the host path is read-only.
    await row.getByRole("button", { name: "Edit" }).click();
    const edit = page.getByRole("dialog", { name: "Edit media root" });
    await expect(edit.getByLabel("Host path")).toHaveAttribute("readonly", "");
    await edit.getByLabel("Name", { exact: true }).fill(renamed);
    await edit.getByRole("button", { name: "Save" }).click();
    const renamedRow = page.getByTestId("root-row").filter({ hasText: renamed });
    await expect(renamedRow).toBeVisible();

    // Check now: the probe runs and the badge shows a real status.
    const [probe] = await Promise.all([
      page.waitForResponse((r) => /\/api\/media-roots\/[^/]+\/probe$/.test(r.url())),
      renamedRow.getByRole("button", { name: "Check now" }).click(),
    ]);
    expect(probe.ok()).toBe(true);
    await expect(renamedRow.getByTestId("root-health")).toHaveText(/^(ok|near_full)$/);

    // Re-apply asks first and names the set count; cancelling queues nothing.
    await renamedRow.getByRole("button", { name: "Re-apply template" }).click();
    const confirm = page.getByRole("dialog", { name: "Re-apply naming template?" });
    await expect(confirm).toContainText("No sets are on");
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toHaveCount(0);

    // Delete.
    await renamedRow.getByRole("button", { name: "Delete" }).click();
    await page
      .getByRole("dialog", { name: "Delete media root" })
      .getByRole("button", { name: "Delete" })
      .click();
    await expect(page.getByTestId("root-row").filter({ hasText: renamed })).toHaveCount(0);
  } finally {
    for (const r of await roots(page)) {
      if (r.name === name || r.name === renamed) {
        await page.request.delete(`/api/media-roots/${r.id}`, {
          headers: { "X-CSRF-Token": await csrf(page) },
        });
      }
    }
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("storage tab: a duplicate name shows a readable error", async ({ page, request }) => {
  await loginAs(page, request);
  await page.goto("/admin/storage");
  await page.getByRole("button", { name: "Add media root" }).click();
  const dialog = page.getByRole("dialog", { name: "Add media root" });
  await dialog.getByLabel("Name", { exact: true }).fill("e2e-seed");
  await dialog.getByLabel("Host path").fill("/nonexistent-t13");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog.getByTestId("root-form-error")).toHaveText("a media root with that name exists");
});
