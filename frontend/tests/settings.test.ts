import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

test("settings change password works end-to-end", async ({ page, request }) => {
  // Change the password of a throwaway user, never the shared seed admin:
  // e2e runs on several workers, and a test that logs in as the admin while
  // this one has its password changed would get a 401.
  await loginAs(page, request);
  const cookies = await page.context().cookies();
  const csrf = cookies.find((c) => c.name === "csrf_token")?.value ?? "";

  const suffix = Date.now().toString(36);
  const invite = await page.request.post("/api/invites", {
    data: { email: `pw-${suffix}@example.test`, role: "user" },
    headers: { "X-CSRF-Token": csrf },
  });
  expect(invite.ok()).toBeTruthy();
  const token = ((await invite.json()) as { invite_link: string }).invite_link.split("/").pop();

  // Redeeming logs the page in as the new user (replaces the admin session).
  const redeem = await page.request.post(`/api/invites/${token}/redeem`, {
    data: { username: `pw${suffix}`, display_name: "PW Tester", password: "initial-password-55" },
  });
  expect(redeem.ok()).toBeTruthy();

  await page.goto("/settings");
  await page.waitForLoadState("networkidle");
  await page.getByRole("tab", { name: /^Security$/i }).click();
  await page.getByLabel(/current password/i).fill("initial-password-55");
  await page.getByLabel(/new password/i).fill("brand-new-password-77");
  await page.getByRole("button", { name: /change password/i }).click();
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(/password updated/i)).toBeVisible();
});

test("admins can set library maintenance notifications; members don't see them", async ({ page, request }) => {
  await loginAs(page, request);
  await page.goto("/settings");
  await page.getByRole("tab", { name: /^Notifications$/i }).click();
  const maintenance = page.getByLabel("Library maintenance (admins)");
  await expect(maintenance).toHaveValue("in_app");
  await expect(maintenance.locator("option")).toHaveText(["In-app", "Off"]);
  const put = page.waitForRequest(
    (r) => r.method() === "PUT" && r.url().endsWith("/api/me/notification-preferences/maintenance"),
  );
  await maintenance.selectOption("off");
  expect((await put).postDataJSON()).toMatchObject({ channel: "off" });
  await maintenance.selectOption("in_app"); // leave the shared admin as it was

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
