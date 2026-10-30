import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// These tests run against the shared "seeded-set" LiveSet. The dev-seed
// endpoint does not clear tracklist rows, so assertions are relative to the
// row count observed at the start of each test rather than absolute.

const rowsOf = (page: Page) => page.locator(".tracks-section .track-row");

async function openSet(page: Page): Promise<void> {
  await page.goto("/sets/seeded-set");
  await page.waitForSelector(".tracks-section");
  // The set page fetches its data in two passes on first load; wait for the
  // network to settle so interactions land on the stable component tree.
  await page.waitForLoadState("networkidle");
}

test.describe("tracklist editor", () => {
  test("M key adds an entry at the playhead", async ({ page, request }) => {
    await loginAs(page, request);
    await openSet(page);
    // Click a neutral element so keyboard events reach the window handler
    // (mirrors set-detail.test.ts, which clicks before keyboard.press).
    await page.locator(".tracks-section h3").click();
    const rows = rowsOf(page);
    const before = await rows.count();
    await page.keyboard.press("m");
    await expect(rows).toHaveCount(before + 1);
  });

  test("paste import materializes parsed entries", async ({ page, request }) => {
    await loginAs(page, request);
    await openSet(page);
    const rows = rowsOf(page);
    const before = await rows.count();

    await page.getByRole("button", { name: "Import" }).click();
    await expect(page.locator("div.modal")).toBeVisible();
    await page
      .locator("div.modal textarea")
      .fill("0:30 Paste One - Track\n5:00 Paste Two - Track");
    await page.getByRole("button", { name: "Parse" }).click();
    await page.getByRole("button", { name: /accept .* selected/i }).click();

    await expect(rows).toHaveCount(before + 2);
    await expect(rows).toContainText(["Paste One - Track", "Paste Two - Track"]);
  });

  test("time-shift dialog reports affected entries and applies", async ({
    page,
    request,
  }) => {
    await loginAs(page, request);
    await openSet(page);

    // Guarantee at least one entry past the shift threshold.
    await page.getByRole("button", { name: "Import" }).click();
    await expect(page.locator("div.modal")).toBeVisible();
    await page.locator("div.modal textarea").fill("9:00 Shift Target - Track");
    await page.getByRole("button", { name: "Parse" }).click();
    await page.getByRole("button", { name: /accept .* selected/i }).click();

    await page.getByRole("button", { name: "Time shift" }).click();
    const dialog = page.locator("div.dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("p.preview")).toContainText(/shift \d+ entr/i);
    await page.getByRole("button", { name: "Apply" }).click();
    await expect(dialog).toBeHidden();
  });
});
