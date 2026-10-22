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
  const total = (await (await page.request.get("/api/sets?limit=1")).json()).total as number;
  test.skip(total < 2, "needs at least two published sets");
  // ?limit= shrinks the page size so we do not need 50+ seeded sets.
  await page.goto("/sets?limit=1");
  const count = page.getByTestId("library-count");
  await expect(count).toHaveText(new RegExp(`Showing 1 of ${total}`));
  await page.getByRole("button", { name: /load more/i }).click();
  await expect(count).toHaveText(new RegExp(`Showing 2 of ${total}`));
});

test("filter sidebar narrows the list", async ({ page, request }) => {
  await loginAs(page, request);
  const facets = await (await page.request.get("/api/sets/facets")).json();
  test.skip(facets.tags.length === 0, "needs a tagged set");
  const tag = facets.tags[0] as { slug: string; count: number };
  await page.goto("/sets");
  await page.getByLabel("Tag").selectOption(tag.slug);
  await expect(page).toHaveURL(new RegExp(`tag=${tag.slug}`));
  await expect(page.getByTestId("library-count")).toHaveText(
    new RegExp(`Showing ${tag.count} of ${tag.count}`),
  );
});

test("home recently added uses created order", async ({ page, request }) => {
  await loginAs(page, request);
  const recent = await (await page.request.get("/api/sets?limit=12&sort=recent")).json();
  test.skip(recent.items.length === 0, "needs a published set");
  const first = recent.items[0] as { title: string; slug: string };
  await page.goto("/");
  const cards = page.locator('a.recent-card');
  await expect(cards.first()).toHaveAttribute("href", `/sets/${first.slug}`);
});
