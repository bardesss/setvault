// frontend/tests/error-page.spec.ts
import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

test.use({ serviceWorkers: "block" });

test("error page renders for an unknown admin route", async ({ page, request }) => {
  await loginAs(page, request);
  await page.goto("/admin/does-not-exist");

  const alert = page.getByRole("alert");
  await expect(alert).toContainText("404");
  await expect(page.getByRole("link", { name: "Back to home" })).toHaveAttribute("href", "/");
});
