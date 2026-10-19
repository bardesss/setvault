import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// SW caches /api GETs; block so route stubs apply.
test.use({ serviceWorkers: "block" });

test("set page shows quality, upgrade history and the switch sends PATCH", async ({ page, request }) => {
  const seed = await loginAs(page, request);
  const url = new RegExp(`/api/sets/${seed.set.slug}$`);

  let detail: Record<string, unknown> | null = null;
  await page.route(url, async (route) => {
    if (route.request().method() === "GET") {
      if (!detail) {
        const real = await route.fetch();
        detail = {
          ...(await real.json()),
          quality: { tier: "lossless", label: "FLAC (Bandcamp)" },
          upgrades_enabled: true,
          // Two events from one transaction share created_at; ids keep them apart.
          upgrade_history: [
            { id: "e2", created_at: "2026-03-05T10:00:00Z", from_label: "MP3 320 kbps (YouTube)", to_label: "FLAC (Bandcamp)" },
            { id: "e1", created_at: "2026-03-05T10:00:00Z", from_label: "MP3 128 kbps (YouTube)", to_label: "MP3 320 kbps (YouTube)" },
          ],
        };
      }
      return route.fulfill({ json: detail });
    }
    const body = route.request().postDataJSON();
    detail = { ...detail, ...body };
    return route.fulfill({ json: detail });
  });

  await page.goto(`/sets/${seed.set.slug}`);
  await expect(page.getByTestId("set-quality-line")).toContainText("FLAC (Bandcamp)");
  await expect(page.getByTestId("upgrade-history").locator("li")).toHaveText([
    /from MP3 320 kbps \(YouTube\) to FLAC \(Bandcamp\)/,
    /from MP3 128 kbps \(YouTube\) to MP3 320 kbps \(YouTube\)/,
  ]);

  const toggle = page.getByLabel("Find better copies automatically");
  await expect(toggle).toBeChecked();
  const patch = page.waitForRequest((r) => r.method() === "PATCH" && url.test(r.url()));
  await toggle.uncheck();
  expect((await patch).postDataJSON()).toEqual({ upgrades_enabled: false });
  await expect(toggle).not.toBeChecked();
});
