import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// SW caches /api GETs; block so reloads see fresh data.
test.use({ serviceWorkers: "block" });

test("webhooks: secret shown once, masked headers, rotate, deliveries, delete", async ({
  page,
  request,
}) => {
  await loginAs(page, request);
  const name = `hook-${randomUUID()}`;
  const headerValue = `secret-value-${randomUUID()}`;

  await page.goto("/admin/webhooks");
  await page.getByRole("button", { name: "+ Empty" }).click();
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Target URL").fill("http://127.0.0.1:9/hook");
  await page.getByLabel("set.published").check();
  await page.getByRole("button", { name: "Add header" }).click();
  await page.getByLabel("Header name").fill("X-Test-Token");
  await page.getByLabel("Header value").fill(headerValue);
  await page.getByRole("button", { name: "Save", exact: true }).click();

  // The secret is shown once.
  const secretDialog = page.getByRole("dialog");
  const secret = await secretDialog.getByTestId("webhook-secret").inputValue();
  expect(secret.length).toBeGreaterThan(16);
  await expect(secretDialog).toContainText("Copy this now. You won't see it again.");
  await secretDialog.getByRole("button", { name: "Close" }).first().click();
  await expect(secretDialog).toBeHidden();

  await page.reload();
  const row = page.getByRole("row").filter({ hasText: name });
  await expect(row).toBeVisible();
  await expect(row).toContainText("Signed");
  const html = await page.content();
  expect(html).not.toContain(secret);
  expect(html).not.toContain(headerValue);

  // Edit headers: name visible, value empty.
  await row.getByRole("button", { name: "Edit headers" }).click();
  await expect(page.getByTestId("header-name").first()).toHaveValue("X-Test-Token");
  await expect(page.getByTestId("header-value").first()).toHaveValue("");
  await expect(page.getByTestId("header-value").first()).toHaveAttribute(
    "placeholder",
    "unchanged",
  );
  await page.getByRole("button", { name: "Cancel" }).click();

  // Rotate secret through the confirm dialog.
  await row.getByRole("button", { name: "Rotate secret" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Rotate secret" }).click();
  const rotated = await page.getByTestId("webhook-secret").inputValue();
  expect(rotated.length).toBeGreaterThan(16);
  expect(rotated).not.toBe(secret);
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).first().click();
  await expect(page.getByRole("dialog")).toBeHidden();

  // Deliveries panel: empty state.
  await row.getByRole("button", { name: "Recent deliveries" }).click();
  await expect(page.getByText("No deliveries yet.")).toBeVisible();

  // Delete through the ConfirmDialog.
  await row.getByRole("button", { name: "Delete" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("row").filter({ hasText: name })).toHaveCount(0);
});
