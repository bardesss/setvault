import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

test.describe("enrichment", () => {
  test("resolve popover opens with mode tabs", async ({ page, request }) => {
    await loginAs(page, request);
    await page.goto("/sets/seeded-set");
    await page.waitForSelector(".tracks-section");
    // The set page fetches its data in two passes; wait for it to settle.
    await page.waitForLoadState("networkidle");

    // Add a raw entry so a Resolve button exists. M adds the entry and opens
    // the edit drawer (after an async create) — wait for it, then dismiss it.
    await page.locator(".tracks-section h3").click();
    await page.keyboard.press("m");
    const drawer = page.locator("div.drawer");
    await expect(drawer).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();

    await page.locator(".tracks-section .track-row .btn-ghost").filter({ hasText: /resolve/i }).first().click();
    await expect(page.locator("div.popover")).toBeVisible();
    await expect(
      page.locator("div.popover .modes button.active"),
    ).toContainText(/metadata/i);
  });
});
