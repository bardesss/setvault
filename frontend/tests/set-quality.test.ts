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
            { id: "e4", created_at: "2026-03-07T10:00:00Z", from_label: "MP3 128 kbps (SoundCloud)", to_label: "FLAC (Bandcamp)", outcome: "merged", tracklist_kept: true },
            { id: "e3", created_at: "2026-03-06T10:00:00Z", from_label: "FLAC (Bandcamp)", to_label: "FLAC (Bandcamp)", outcome: "merged" },
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
    /Merged a duplicate copy \(MP3 128 kbps \(SoundCloud\)\) into this set on .*; its tracklist stayed with the recycled copy$/,
    /Merged a duplicate copy \(FLAC \(Bandcamp\)\) into this set on [^;]*$/,
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

test("set page hints when automatic upgrades are off for the whole library", async ({ page, request }) => {
  const seed = await loginAs(page, request);
  const url = new RegExp(`/api/sets/${seed.set.slug}$`);
  await page.route(url, async (route) => {
    const real = await route.fetch();
    return route.fulfill({
      json: { ...(await real.json()), upgrades_enabled: true, auto_upgrades_enabled: false },
    });
  });

  await page.goto(`/sets/${seed.set.slug}`);
  await expect(page.getByTestId("upgrades-library-off")).toHaveText(
    "Automatic upgrades are switched off for the whole library",
  );
});
