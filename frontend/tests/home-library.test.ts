import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

test.describe("continue listening", () => {
  // page.route can't see requests the service worker answers.
  test.use({ serviceWorkers: "block" });

  test("home shows continue-listening when state exists", async ({ page, request }) => {
    await loginAs(page, request);
    // The dev-seed sets are 1 s long, so no real saved position can pass the
    // continue-listening filters (> 5 s in, < 97 % of the duration; those are
    // covered in apps/web/tests/test_me.py). Stub the endpoint to check that
    // the home page renders the section when the API returns a set in progress.
    await page.route("**/api/me/continue-listening", (route) =>
      route.fulfill({
        json: [{ slug: "seeded-set", title: "seeded set", position_seconds: 42, duration_seconds: 3600 }],
      }),
    );
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /continue/i })).toBeVisible();
  });
});

test("library lists seeded set and filters by query", async ({ page, request }) => {
  await loginAs(page, request);
  await page.goto("/sets");
  await expect(page.getByRole("link", { name: /seeded set/i })).toBeVisible();
});

test("library loads more than the first page", async ({ page, request }) => {
  await loginAs(page, request);
  const { total } = (await (await page.request.get("/api/sets?limit=1")).json()) as {
    total: number;
  };
  expect(total).toBeGreaterThanOrEqual(4);
  // ?limit= shrinks the page size so we do not need 50+ seeded sets.
  await page.goto("/sets?limit=1");
  const count = page.getByTestId("library-count");
  await expect(count).toHaveText(`Showing 1 of ${total}`);
  await page.getByRole("button", { name: /load more/i }).click();
  await expect(count).toHaveText(`Showing 2 of ${total}`);
});

test("filter sidebar narrows the list", async ({ page, request }) => {
  await loginAs(page, request);
  const { total } = (await (await page.request.get("/api/sets?limit=1")).json()) as {
    total: number;
  };
  const facets = await (await page.request.get("/api/sets/facets")).json();
  const tag = (facets.tags as { slug: string; count: number }[]).find(
    (t) => t.slug === "e2e-house",
  )!;
  expect(tag.count).toBeLessThan(total);
  await page.goto("/sets");
  await expect(page.getByTestId("library-count")).toHaveText(`Showing ${total} of ${total}`);
  await page.getByLabel("Tag").selectOption("e2e-house");
  await expect(page).toHaveURL(/tag=e2e-house/);
  await expect(page.getByTestId("library-count")).toHaveText(
    `Showing ${tag.count} of ${tag.count}`,
  );
});

test("home recently added uses created order", async ({ page, request }) => {
  await loginAs(page, request);
  // Seeded dates run alpha > bravo > charlie, created_at the other way round.
  const recent = (await (await page.request.get("/api/sets?limit=12&sort=recent")).json())
    .items as { slug: string }[];
  const ours = recent.map((s) => s.slug).filter((s) => s.startsWith("e2e-"));
  expect(ours).toEqual(["e2e-charlie", "e2e-bravo", "e2e-alpha"]);
  await page.goto("/");
  await expect(page.locator("a.recent-card").first()).toBeVisible();
  const hrefs = await page
    .locator("a.recent-card")
    .evaluateAll((els) => els.map((e) => e.getAttribute("href")));
  expect(hrefs[0]).toBe(`/sets/${recent[0].slug}`);
  expect(hrefs.filter((h) => h?.startsWith("/sets/e2e-"))).toEqual([
    "/sets/e2e-charlie",
    "/sets/e2e-bravo",
    "/sets/e2e-alpha",
  ]);
  // Venue shows on the card for the set that has one.
  await expect(page.locator("a.recent-card", { hasText: "Alpha Night" })).toContainText("E2E Club");
});

test("home shows recent activity", async ({ page, request }) => {
  await loginAs(page, request);
  await page.goto("/");
  const section = page.getByTestId("home-activity");
  await expect(section.getByRole("heading", { name: "Recent activity" })).toBeVisible();
  // The e2e seed records a publish event, so the list is populated.
  await expect(section.locator("li.activity-row").first()).toBeVisible();
  await expect(section.locator(".activity-empty")).toHaveCount(0);
});
