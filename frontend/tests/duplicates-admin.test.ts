// frontend/tests/duplicates-admin.test.ts
import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// SW caches /api GETs; block so route stubs apply.
test.use({ serviceWorkers: "block" });

test("admin duplicates tab lists held duplicates and keeps one", async ({ page, request }) => {
  await loginAs(page, request);

  await page.route(/\/api\/admin\/duplicates$/, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      items: [{
        id: "33333333-0000-0000-0000-000000000003",
        slug: "upload-dupe",
        title: "Second copy.flac",
        source_type: "upload",
        duration_seconds: 3725,
        created_at: "2026-10-17T10:00:00+00:00",
        original: { slug: "the-original", title: "The Original", status: "published", duration_seconds: 3724 },
      }],
    }) }),
  );
  let kept = false;
  await page.route(/\/api\/admin\/duplicates\/upload-dupe\/keep$/, (r) => {
    kept = true;
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ slug: "upload-dupe", status: "published" }) });
  });

  await page.goto("/admin/duplicates");
  await page.waitForLoadState("networkidle");
  await expect(page.getByText("Second copy.flac")).toBeVisible();
  await expect(page.getByRole("link", { name: "The Original" })).toHaveAttribute("href", "/sets/the-original");
  await expect(page.getByText("1:02:05")).toBeVisible();

  await page.getByRole("button", { name: /keep/i }).click();
  await expect.poll(() => kept).toBe(true);
  await expect(page.getByText("No duplicates waiting for review.")).toBeVisible();
});

test("admin duplicates tab marks sets matched by the backfill", async ({ page, request }) => {
  await loginAs(page, request);

  await page.route(/\/api\/admin\/duplicates$/, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      items: [{
        id: "33333333-0000-0000-0000-000000000004",
        slug: "published-twin",
        title: "Published twin",
        source_type: "upload",
        duration_seconds: 3725,
        created_at: "2026-10-17T10:00:00+00:00",
        status: "published",
        reason: "matched by backfill",
        original: { slug: "the-original", title: "The Original", status: "published", duration_seconds: 3724 },
      }],
    }) }),
  );

  await page.goto("/admin/duplicates");
  await expect(page.getByText("Published twin")).toBeVisible();
  await expect(page.getByTestId("dup-reason")).toHaveText("Published · matched by backfill");
  await expect(page.getByRole("button", { name: "Keep", exact: true })).toBeVisible();
});
