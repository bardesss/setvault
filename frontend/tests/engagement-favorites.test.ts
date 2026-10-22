import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

test("favourite toggles and appears on /me/favorites", async ({ page, request }) => {
  const seed = await loginAs(page, request);
  await page.goto(`/sets/${seed.set.slug}`);

  const btn = page.locator("button.favorite");
  await expect(btn).toBeEnabled({ timeout: 15_000 });

  // Normalise to unpressed so the test is deterministic on shared state.
  if ((await btn.getAttribute("aria-pressed")) === "true") {
    await btn.click();
    await expect(btn).toHaveAttribute("aria-pressed", "false");
  }

  await btn.click();
  await expect(btn).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  const again = page.locator("button.favorite");
  await expect(again).toBeEnabled({ timeout: 15_000 });
  await expect(again).toHaveAttribute("aria-pressed", "true");

  await page.goto("/me/favorites");
  await expect(page.locator("h1")).toContainText(/favou?rites/i);
  await expect(page.locator(`a[href="/sets/${seed.set.slug}"]`).first()).toBeVisible();

  // Leave no favourite behind on the shared seed user.
  await page.goto(`/sets/${seed.set.slug}`);
  const cleanup = page.locator("button.favorite");
  await expect(cleanup).toBeEnabled({ timeout: 15_000 });
  await cleanup.click();
  await expect(cleanup).toHaveAttribute("aria-pressed", "false");
});

test("nav shows Favorites link", async ({ page, request }) => {
  await loginAs(page, request);
  await page.goto("/");
  const link = page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Favorites" });
  await expect(link).toHaveAttribute("href", "/me/favorites");
});
