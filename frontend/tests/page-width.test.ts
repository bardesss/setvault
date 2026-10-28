import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// No page may scroll sideways: a wide child (top bar, admin table) has to
// shrink, wrap or scroll inside its own box.
const PAGES = [
  "/", "/sets", "/sets/seeded-set", "/artists", "/search", "/playlists", "/settings",
  "/admin/storage", "/admin/users", "/admin/quality",
];

// Dutch labels run longest, so the narrowest width is checked in Dutch too.
const CASES = [
  { width: 375, locale: "en-US" },
  { width: 768, locale: "en-US" },
  { width: 1280, locale: "en-US" },
  { width: 375, locale: "nl-NL" },
];

for (const { width, locale } of CASES) {
  test(`no horizontal page scroll at ${width}px (${locale})`, async ({ browser, baseURL, request }) => {
    const context = await browser.newContext({
      baseURL, locale, serviceWorkers: "block", viewport: { width, height: 800 },
    });
    const page = await context.newPage();
    await loginAs(page, request);
    for (const path of PAGES) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const { scroll, client } = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }));
      expect(scroll, `${path} at ${width}px`).toBeLessThanOrEqual(client);
      const main = await page.evaluate(() => {
        const m = document.querySelector("main.main");
        return m ? m.scrollWidth - m.clientWidth : 0;
      });
      expect(main, `${path} main pane at ${width}px`).toBeLessThanOrEqual(0);
    }
    await context.close();
  });
}
