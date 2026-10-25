// frontend/tests/drafts-admin.test.ts
import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// SW caches /api GETs; block so route stubs apply.
test.use({ serviceWorkers: "block", timezoneId: "UTC" });

const draft = (over: Record<string, unknown>) => ({
  id: crypto.randomUUID(),
  source_type: "url_rip",
  duration_seconds: 3725,
  created_at: "2026-06-17T14:21:54+00:00",
  ready: false,
  processing: false,
  rip_status: null,
  error: null,
  duplicate_of: null,
  ...over,
});

test("admin drafts tab publishes a ready draft and discards a failed one", async ({ page, request }) => {
  await loginAs(page, request);

  await page.route(/\/api\/admin\/drafts$/, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      items: [
        draft({ slug: "ready-one", title: "Ready one", ready: true }),
        draft({ slug: "broken-one", title: "Broken one", rip_status: "failed", error: "ffmpeg exited 1" }),
        draft({ slug: "busy-one", title: "Busy one", processing: true, rip_status: "transcoding" }),
      ],
    }) }),
  );
  const calls: string[] = [];
  await page.route(/\/api\/admin\/drafts\/[^/]+\/(publish|discard)$/, (r) => {
    calls.push(new URL(r.request().url()).pathname);
    return r.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });

  await page.goto("/admin/drafts");
  await expect(page.getByRole("heading", { name: "Drafts" })).toBeVisible();
  const rows = page.getByTestId("draft-row");
  await expect(rows).toHaveCount(3);

  const ready = rows.filter({ hasText: "Ready one" });
  const broken = rows.filter({ hasText: "Broken one" });
  const busy = rows.filter({ hasText: "Busy one" });
  await expect(broken.getByTestId("draft-state")).toHaveText("Rip failed");
  await expect(broken.getByTestId("draft-error")).toHaveText("ffmpeg exited 1");
  await expect(broken.getByRole("button", { name: "Publish" })).toBeDisabled();
  await expect(busy.getByRole("button", { name: "Discard" })).toBeDisabled();

  await ready.getByRole("button", { name: "Publish" }).click();
  await expect(rows).toHaveCount(2);

  await broken.getByRole("button", { name: "Discard" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Discard" }).click();
  await expect(rows).toHaveCount(1);

  expect(calls).toEqual([
    "/api/admin/drafts/ready-one/publish",
    "/api/admin/drafts/broken-one/discard",
  ]);
});

test("admin drafts tab says so when there are none", async ({ page, request }) => {
  await loginAs(page, request);
  await page.route(/\/api\/admin\/drafts$/, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) }),
  );
  await page.goto("/admin/drafts");
  await expect(page.getByText("No drafts. Everything you have is in Library.")).toBeVisible();
});
