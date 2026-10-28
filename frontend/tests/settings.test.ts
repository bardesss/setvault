import { expect, test } from "@playwright/test";
import { createMember, loginAs } from "./helpers/auth";

test("settings change password works end-to-end", async ({ page, request }) => {
  // Change the password of a throwaway user, never the shared seed admin:
  // e2e runs on several workers, and a test that logs in as the admin while
  // this one has its password changed would get a 401.
  await createMember(page, request);
  await page.goto("/settings");
  await page.waitForLoadState("networkidle");
  await page.getByRole("tab", { name: /^Security$/i }).click();
  await page.getByLabel(/current password/i).fill("initial-password-55");
  await page.getByLabel(/new password/i).fill("brand-new-password-77");
  await page.getByRole("button", { name: /change password/i }).click();
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(/password updated/i)).toBeVisible();
});

test.describe("maintenance notifications", () => {
  // SW caches /api GETs; block so the /api/auth/me stub applies.
  test.use({ serviceWorkers: "block" });

  test("admins can set library maintenance notifications; members don't see them", async ({ page, request }) => {
    await loginAs(page, request);
    await page.goto("/settings");
    await page.getByRole("tab", { name: /^Notifications$/i }).click();
    const maintenance = page.getByLabel("Library maintenance (admins)");
    await expect(maintenance.locator("option")).toHaveText(["In-app", "Off"]);
    const choose = async (channel: string) => {
      const put = page.waitForRequest(
        (r) => r.method() === "PUT" && r.url().endsWith("/api/me/notification-preferences/maintenance"),
      );
      await maintenance.selectOption(channel);
      expect((await put).postDataJSON()).toMatchObject({ channel });
    };
    await choose("off");
    await choose("in_app"); // leave the shared admin at the default
    await page.waitForLoadState("networkidle");

    // A member's session: no maintenance row.
    await page.route(/\/api\/auth\/me$/, async (route) => {
      const real = await route.fetch();
      return route.fulfill({ json: { ...(await real.json()), role: "user" } });
    });
    await page.goto("/settings");
    await page.getByRole("tab", { name: /^Notifications$/i }).click();
    await expect(page.getByLabel("Set upgraded to better quality")).toBeVisible();
    await expect(page.getByLabel("Library maintenance (admins)")).toHaveCount(0);
  });
});
