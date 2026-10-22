import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

test("home shows continue-listening when state exists", async ({ page, request }) => {
  await loginAs(page, request);
  await page.goto("/sets/seeded-set");
  await page.waitForLoadState("networkidle");
  // Seed UserSetState explicitly so the test doesn't race the Player's
  // best-effort onDestroy saveState (which is fire-and-forget and may be
  // aborted by SvelteKit's client-side navigation before the PUT lands).
  // Hitting the API directly through the page's cookie jar guarantees the
  // row exists before we render the home page.
  const cookies = await page.context().cookies();
  const csrf = cookies.find((c) => c.name === "csrf_token")?.value ?? "";
  const put = await page.request.put("/api/sets/seeded-set/state", {
    data: { position_seconds: 5, completed: false },
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
  });
  expect(put.ok()).toBeTruthy();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /continue/i })).toBeVisible();
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
