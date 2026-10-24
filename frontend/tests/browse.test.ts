import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// "track-link" is seeded for this file (dev_seed.py: TRACK_SET_SLUG): one
// resolved tracklist entry, "Browse Anthem" by E2E Resident. Read-only here.
test.use({ serviceWorkers: "block" });

test.beforeEach(async ({ page, request }) => {
  await loginAs(page, request);
});

test("the nav opens the artists list, search narrows it and sort lands in the URL", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Artists" }).click();
  await expect(page).toHaveURL(/\/artists$/);
  await expect(page.getByRole("heading", { name: "Artists" })).toBeVisible();
  await expect(page.getByRole("link", { name: /E2E Resident/ })).toBeVisible();

  await page.getByLabel("Search by name").fill("zzz-no-such-artist");
  await expect(page).toHaveURL(/q=zzz-no-such-artist/);
  await expect(page.getByText("Nothing matches.")).toBeVisible();

  await page.getByLabel("Search by name").fill("E2E Resident");
  await expect(page).toHaveURL(/q=E2E(\+|%20)Resident/);
  await expect(page.getByTestId("browse-count")).toHaveText("Showing 1 of 1");
  await expect(page.getByRole("link", { name: /E2E Resident/ })).toBeVisible();

  await page.getByLabel("Sort by").selectOption("sets");
  await expect(page).toHaveURL(/sort=sets/);
});

test("the other browse pages list their entities", async ({ page }) => {
  await page.goto("/venues");
  await expect(page.getByRole("link", { name: /E2E Club/ })).toBeVisible();
});

test("a resolved tracklist entry links to the library filtered by that track", async ({ page }) => {
  await page.goto("/sets/track-link");
  await page.getByRole("link", { name: "Other sets with this track" }).click();
  await expect(page).toHaveURL(/\/sets\?track=[0-9a-f-]{36}$/);

  const chip = page.getByTestId("track-chip");
  await expect(chip).toContainText("Track: Browse Anthem — E2E Resident");
  await expect(page.getByTestId("library-count")).toHaveText("Showing 1 of 1");
  await expect(page.getByRole("link", { name: /Track Link Set/ })).toBeVisible();

  await chip.getByRole("button", { name: "Remove track filter" }).click();
  await expect(page).not.toHaveURL(/track=/);
  await expect(chip).toHaveCount(0);
  await expect(page.getByTestId("library-count")).not.toHaveText("Showing 1 of 1");
});
