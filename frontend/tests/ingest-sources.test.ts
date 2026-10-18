import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// SW caches /api GETs and its fetches bypass page.route; block so stubs apply.
test.use({ serviceWorkers: "block" });

test("multi-source search lists candidates with chips, an unavailable notice, and ingest fires a rip", async ({
  page,
  request,
}) => {
  await loginAs(page, request);

  // Stub the source search — two candidates from different sources + one errored source.
  await page.route("**/api/ingest-sources/search", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            source_kind: "youtube",
            external_id: "vid1",
            title: "YT Stub Set",
            uploader: "DJ X",
            duration_seconds: 3600,
            thumbnail_url: null,
            webpage_url: "https://www.youtube.com/watch?v=vid1",
            already_in_library: false,
          },
          {
            source_kind: "soundcloud",
            external_id: "111",
            title: "SC Stub Set",
            uploader: "DJ S",
            duration_seconds: 1800,
            thumbnail_url: null,
            webpage_url: "https://soundcloud.com/dj-s/sc-stub",
            already_in_library: false,
          },
        ],
        errored_sources: ["mixcloud"],
      }),
    }),
  );

  // Stub the rip submit — return a canned RipJob matching submitUrl's shape.
  let ripCalled = false;
  await page.route("**/api/sets/url-rip", (route) => {
    ripCalled = true;
    return route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: "00000000-0000-0000-0000-000000000001",
        live_set_id: null,
        live_set_slug: null,
        source_url: "https://www.youtube.com/watch?v=vid1",
        source_external_id: "vid1",
        source_platform: "youtube",
        status: "queued",
        progress_pct: 0,
        message: null,
        error_text: null,
        probed_metadata: {},
        ytdlp_version: "2026.3.17",
        created_at: new Date().toISOString(),
        started_at: null,
        finished_at: null,
      }),
    });
  });

  await page.goto("/search");
  await page.waitForLoadState("networkidle");

  // Switch to the Sources tab. On a cold dev server the first click can land
  // before Svelte hydration attaches the handler (a no-op), so retry the click
  // until the sources panel actually renders.
  const sourcesTab = page.getByRole("tab", { name: /^Sources$/i });
  const sourceInput = page.getByPlaceholder(/Search all sources/i);
  await expect(sourcesTab).toBeVisible();
  await expect(async () => {
    await sourcesTab.click();
    await expect(sourceInput).toBeVisible({ timeout: 1_000 });
  }).toPass({ timeout: 15_000 });

  // Fill the source-search box and submit (submit button is "Search").
  await sourceInput.fill("best set");
  await page.getByRole("button", { name: /^Search$/i }).click();

  // Both stubbed candidates should appear.
  await expect(page.getByText("YT Stub Set")).toBeVisible({ timeout: 5_000 });
  await expect(page.getByText("SC Stub Set")).toBeVisible();

  // The SoundCloud candidate carries a source chip.
  await expect(page.getByText("SoundCloud")).toBeVisible();

  // The errored source surfaces in the partial-unavailable notice.
  await expect(page.getByText(/Mixcloud/i)).toBeVisible();

  // Ingest the first (YouTube) candidate and assert it flips to "In library".
  await page.getByRole("button", { name: /^Ingest$/i }).first().click();
  await expect(page.getByText(/In library/i)).toBeVisible({ timeout: 5_000 });
  expect(ripCalled).toBe(true);
});
