import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// SW caches /api GETs; block so route stubs apply.
test.use({ serviceWorkers: "block" });

const json = (body: unknown) => ({
  status: 200, contentType: "application/json", body: JSON.stringify(body),
});

test("quality tab reorders tiers and saves the new order", async ({ page, request }) => {
  await loginAs(page, request);

  const settings = {
    audit_retention_days: 90,
    monitors_allow_all_users: false,
    monitor_interval_seconds: 3600,
    single_user_auto_login: false,
    quality_tiers_order: ["lossless", "high", "good", "ok", "low"],
    quality_cutoff: "lossless",
    auto_upgrades_enabled: true,
    upgrade_search_schedule: "weekly",
  };
  let put: Record<string, unknown> | null = null;
  await page.route(/\/api\/admin\/settings$/, (r) => {
    if (r.request().method() === "PUT") {
      put = r.request().postDataJSON();
      return r.fulfill(json({ ...settings, ...put }));
    }
    return r.fulfill(json(settings));
  });
  await page.route(/\/api\/admin\/maintenance\/quality-backfill$/, (r) =>
    r.fulfill(json({ to_fingerprint: 4, to_measure: 7 })),
  );

  await page.goto("/admin/quality");
  await expect(page.getByTestId("backfill-counts")).toContainText("4 to fingerprint, 7 to measure");

  await page.getByRole("button", { name: "Move High up" }).click();
  await page.getByLabel("Upgrade search").selectOption("daily");
  await page.getByRole("button", { name: "Save" }).click();

  await expect.poll(() => put).not.toBeNull();
  expect(put).toMatchObject({
    quality_tiers_order: ["high", "lossless", "good", "ok", "low"],
    upgrade_search_schedule: "daily",
    auto_upgrades_enabled: true,
  });
});

test("wanted tab lists a set and posts Search now", async ({ page, request }) => {
  await loginAs(page, request);

  await page.route(/\/api\/admin\/wanted\?/, (r) =>
    r.fulfill(json({ items: [{
      id: "44444444-0000-0000-0000-000000000004",
      slug: "old-mix",
      title: "Old Mix",
      quality_label: "MP3 128 kbps (YouTube)",
      quality_tier: "ok",
      last_upgrade_search_at: null,
      last_event: { outcome: "rejected", reason: "not better", created_at: "2026-10-18T10:00:00+00:00" },
    }] })),
  );
  let searched = false;
  await page.route(/\/api\/admin\/wanted\/old-mix\/search$/, (r) => {
    searched = true;
    return r.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ status: "queued" }) });
  });

  await page.goto("/admin/wanted");
  await expect(page.getByRole("link", { name: "Old Mix" })).toBeVisible();
  await expect(page.getByText("MP3 128 kbps (YouTube)")).toBeVisible();
  await expect(page.getByText("Rejected: not better")).toBeVisible();

  await page.getByRole("button", { name: "Search now" }).click();
  await expect.poll(() => searched).toBe(true);
  await expect(page.getByText("Queued")).toBeVisible();
});
