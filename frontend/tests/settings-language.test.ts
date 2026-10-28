import { expect, test } from "@playwright/test";
import { createMember } from "./helpers/auth";

// A throwaway member, never the shared seed admin: other workers rely on the
// admin's account staying in English.
test("switching to Nederlands changes the UI and persists", async ({ page, request }) => {
  await createMember(page, request);
  await page.goto("/settings");
  const select = page.getByLabel("Language");
  const saved = page.waitForResponse(
    (r) => r.url().endsWith("/api/me") && r.request().method() === "PATCH",
  );
  await select.selectOption("nl");
  expect((await saved).status()).toBe(204);

  await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe("nl");
  await expect(page.locator(".rail").getByRole("link", { name: "Bibliotheek" })).toBeVisible();

  // The choice is on the account: a fresh device (no cached choice) gets it too.
  await page.evaluate(() => localStorage.removeItem("setvault.locale"));
  await page.reload();
  await expect(page.locator(".rail").getByRole("link", { name: "Bibliotheek" })).toBeVisible();
  await expect(page.getByLabel("Taal")).toHaveValue("nl");

  // Back to following the browser (en-US in e2e).
  await page.getByLabel("Taal").selectOption("");
  await expect(page.locator(".rail").getByRole("link", { name: "Library" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe("en");
});

test.describe("signed out", () => {
  test.use({ locale: "nl-NL" });

  test("the login page follows the browser language and saves nothing", async ({ page }) => {
    let patched = false;
    page.on("request", (r) => {
      if (r.method() === "PATCH" && r.url().endsWith("/api/me")) patched = true;
    });
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Inloggen" })).toBeVisible();
    await expect(page.getByLabel("Language")).toHaveCount(0);
    await expect(page.getByLabel("Taal")).toHaveCount(0);
    expect(patched).toBe(false);
  });
});

test.describe("broken language file", () => {
  // page.route can't see requests the service worker makes.
  test.use({ serviceWorkers: "block" });

  test("falls back to English when a language file fails to load", async ({ page }) => {
    let blocked = false;
    // Dev server: /src/lib/i18n/locales/nl.json?import; build: a hashed nl-*.js chunk.
    await page.route(/\/locales\/nl\.json|\/nl-[\w-]+\.js(\?|$)/, (route) => {
      blocked = true;
      return route.abort();
    });
    await page.addInitScript(() => localStorage.setItem("setvault.locale", "nl"));
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(blocked).toBe(true);
  });
});

test("a stale cached language falls back to the browser language", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("setvault.locale", "xx"));
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe("en");
});
