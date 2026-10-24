import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// SW caches /api GETs; block so route stubs apply.
test.use({ serviceWorkers: "block" });

test("backups tab: status, keep setting, run now, files, full export", async ({ page, request }) => {
  await loginAs(page, request);

  // backup_keep is global config shared with other specs (2 CI workers):
  // restore the original value whatever happens.
  const original = (await (await page.request.get("/api/admin/settings")).json()) as {
    backup_keep: number;
  };

  try {
    // Never run a real pg_dump in CI.
    let runPosts = 0;
    await page.route(/\/api\/admin\/backups\/run$/, (r) => {
      if (r.request().method() === "POST") {
        runPosts += 1;
        return r.fulfill({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({ job_id: "stub" }),
        });
      }
      return r.continue();
    });

    await page.goto("/admin/backups");
    await expect(page.getByRole("heading", { name: "Backups" })).toBeVisible();
    await expect(page.getByTestId("backup-status")).toBeVisible();
    await expect(page.getByTestId("backup-tz")).toContainText("UTC");

    // Change keep to 7, save, reload.
    const keep = page.getByLabel("Keep the newest");
    await keep.fill("7");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Backup settings saved")).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("Keep the newest")).toHaveValue("7");

    // Back up now: request goes out, toast shows.
    await page.getByRole("button", { name: "Back up now" }).click();
    await expect(page.getByText("Backup started")).toBeVisible();
    expect(runPosts).toBe(1);

    // Files: rows or the empty state.
    const rows = page.getByTestId("backup-file");
    const empty = page.getByTestId("backup-empty");
    await expect(rows.first().or(empty)).toBeVisible();

    await expect(page.getByRole("link", { name: "Full export" })).toHaveAttribute(
      "href",
      "/api/admin/backup",
    );
  } finally {
    await page.request.put("/api/admin/settings", {
      data: { backup_keep: original.backup_keep },
      headers: { "X-CSRF-Token": await csrf(page) },
    });
  }
});

async function csrf(page: import("@playwright/test").Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name === "csrf_token")?.value ?? "";
}
