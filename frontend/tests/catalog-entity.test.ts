// frontend/tests/catalog-entity.test.ts
import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// SW caches /api GETs; block so route stubs apply.
test.use({ serviceWorkers: "block" });

const artist = {
  id: "00000000-0000-0000-0000-0000000000aa",
  name: "Stub Artist", slug: "stub-artist",
  country: "BE", bio: "original bio", aliases: [], image_url: null,
};

test("artist page lists sets and supports inline edit", async ({ page, request }) => {
  await loginAs(page, request);

  await page.route(/\/api\/catalog\/artists\/stub-artist\/sets/, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      items: [{ slug: "set-1", title: "Stub Set", artists: [{ name: "Stub Artist", slug: "stub-artist" }], venue: null, date: null, duration_seconds: null }],
    }) }),
  );
  await page.route(/\/api\/catalog\/artists\/stub-artist$/, (route) => {
    if (route.request().method() === "PATCH") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...artist, bio: "edited bio" }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(artist) });
  });

  await page.goto("/artists/stub-artist");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "Stub Artist" })).toBeVisible();
  await expect(page.getByText("Stub Set")).toBeVisible();

  await page.getByRole("button", { name: /edit/i }).click();
  await page.getByLabel(/bio/i).fill("edited bio");
  await page.getByRole("button", { name: /^save$/i }).click();
  await expect(page.getByText("edited bio")).toBeVisible();
});

test("members see no Edit or Enrich on entity pages", async ({ page, request }) => {
  await loginAs(page, request);
  await page.route(/\/api\/auth\/me$/, async (route) => {
    const real = await route.fetch();
    return route.fulfill({ json: { ...(await real.json()), role: "user" } });
  });
  await page.route(/\/api\/catalog\/artists\/stub-artist\/sets/, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) }),
  );
  await page.route(/\/api\/catalog\/artists\/stub-artist$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(artist) }),
  );
  await page.goto("/artists/stub-artist");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "Stub Artist" })).toBeVisible();
  await expect(page.getByRole("button", { name: /edit/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /enrich/i })).toHaveCount(0);
});
