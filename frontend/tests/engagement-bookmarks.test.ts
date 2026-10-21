import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

test("/me/bookmarks page renders heading", async ({ page, request }) => {
  await loginAs(page, request);
  await page.goto("/me/bookmarks");
  await expect(page.locator("h1")).toContainText(/bookmarks/i);
});

test("set-level bookmark toggles via button", async ({ page, request }) => {
  const seed = await loginAs(page, request);
  await page.goto(`/sets/${seed.set.slug}`);

  // BookmarkButton lives behind the Bookmarks tab in the SidePanel and only
  // mounts (and fetches its list) once the tab opens.
  await page.getByRole("tab", { name: "Bookmarks" }).click();

  // The button stays disabled until its initial bookmark list has loaded.
  // Reading aria-pressed before then could see "false" while a bookmark left
  // by an earlier test is still on its way, flipping the toggle's direction.
  const btn = page.locator("button.bookmark");
  await expect(btn).toBeEnabled({ timeout: 15_000 });

  const initial = await btn.getAttribute("aria-pressed");
  await btn.click();

  // State must change to the opposite of whatever it was. Direction-
  // agnostic so the test survives whatever leftover state exists.
  const expected = initial === "true" ? "false" : "true";
  await expect(btn).toHaveAttribute("aria-pressed", expected, { timeout: 10_000 });
});
