import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// The PWA service worker caches /api GETs (network-first), which would bypass
// page.route stubbing for the rip-jobs listing. Block it so stubs apply.
test.use({ serviceWorkers: "block" });

function ripJob(overrides: Record<string, unknown> = {}) {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    live_set_id: null,
    live_set_slug: null,
    source_url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    source_external_id: "dQw4w9WgXcQ",
    source_platform: "youtube",
    status: "downloading",
    progress_pct: 42,
    message: null,
    error_text: null,
    probed_metadata: { title: "My Download Title" },
    ytdlp_version: "2026.3.17",
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}

test("downloads page lists my rip jobs with status", async ({ page, request }) => {
  await loginAs(page, request);

  await page.route(/\/api\/me\/rip-jobs/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [ripJob()] }),
    }),
  );

  await page.goto("/me/downloads");
  await page.waitForLoadState("networkidle");

  await expect(page.getByText("My Download Title")).toBeVisible({ timeout: 5_000 });
  await expect(page.getByText("Downloading")).toBeVisible();
  await expect(page.getByText("42%", { exact: true })).toBeVisible();
});

test("a failed download shows a Retry button that re-submits the URL", async ({ page, request }) => {
  await loginAs(page, request);

  await page.route(/\/api\/me\/rip-jobs/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [ripJob({ status: "failed", error_text: "no default ingest root", progress_pct: 0 })],
      }),
    }),
  );

  let submitted = false;
  await page.route(/\/api\/sets\/url-rip/, (route) => {
    submitted = true;
    route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(ripJob({ id: "00000000-0000-0000-0000-000000000002", status: "queued" })),
    });
  });

  await page.goto("/me/downloads");
  await page.waitForLoadState("networkidle");

  await page.getByRole("button", { name: /retry/i }).click();

  await expect.poll(() => submitted).toBe(true);
  await expect(page.getByText("Queued")).toBeVisible({ timeout: 5_000 });
});

test("'Clear finished' removes finished rips and issues a DELETE", async ({ page, request }) => {
  await loginAs(page, request);

  let cleared = false;
  await page.route(/\/api\/me\/rip-jobs(\?|$)/, (route) => {
    if (route.request().method() === "DELETE") {
      cleared = true;
      return route.fulfill({ status: 204, body: "" });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          ripJob({ id: "11111111-0000-0000-0000-000000000001", status: "failed", error_text: "nope", probed_metadata: { title: "Finished One" } }),
          ripJob({ id: "22222222-0000-0000-0000-000000000002", status: "downloading", probed_metadata: { title: "Active One" } }),
        ],
      }),
    });
  });

  await page.goto("/me/downloads");
  await page.waitForLoadState("networkidle");
  await expect(page.getByText("Finished One")).toBeVisible({ timeout: 5_000 });

  await page.getByRole("button", { name: /clear finished/i }).click();

  await expect.poll(() => cleared).toBe(true);
  await expect(page.getByText("Finished One")).toBeHidden();
  await expect(page.getByText("Active One")).toBeVisible();
});

test("downloads page shows an empty state when there are no rips", async ({ page, request }) => {
  await loginAs(page, request);

  await page.route(/\/api\/me\/rip-jobs/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [] }),
    }),
  );

  await page.goto("/me/downloads");
  await page.waitForLoadState("networkidle");

  await expect(page.getByText(/no downloads yet/i)).toBeVisible({ timeout: 5_000 });
});
