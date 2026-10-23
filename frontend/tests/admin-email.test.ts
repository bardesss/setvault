import { expect, test, type Page } from "@playwright/test";
import { loginAs } from "./helpers/auth";

test.use({ serviceWorkers: "block" });

interface ConnectorRow {
  id: string;
  kind: string;
}

async function csrf(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  return cookies.find((c) => c.name === "csrf_token")?.value ?? "";
}

async function smtpConnectors(page: Page): Promise<ConnectorRow[]> {
  const body = (await (await page.request.get("/api/connectors")).json()) as { items: ConnectorRow[] };
  return body.items.filter((c) => c.kind === "smtp");
}

test("email tab: save settings, password set indicator, dry-run test send", async ({ page, request }) => {
  await loginAs(page, request);
  // The tab manages the first SMTP connector. Never touch one this test did not create.
  test.skip((await smtpConnectors(page)).length > 0, "an SMTP connector already exists");

  // Only ever delete the connector this test created, never another worker's.
  let ownId: string | null = null;
  try {
    await page.goto("/admin/email");
    // The first hit of a route compiles it on the dev server.
    await expect(page.getByRole("heading", { name: "Email" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Save the settings first")).toBeVisible();

    await page.getByLabel("Host", { exact: true }).fill("smtp.t13.test");
    await page.getByLabel("Port", { exact: true }).fill("2525");
    await page.getByLabel("Security").selectOption("ssl");
    await page.getByLabel("From address").fill("noreply@t13.test");
    const [created] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/api/connectors") && r.request().method() === "POST"),
      page.getByRole("button", { name: "Save" }).click(),
    ]);
    ownId = ((await created.json()) as { id: string }).id;
    await expect(page.getByText("Email settings saved")).toBeVisible();

    await page.reload();
    await expect(page.getByLabel("Host", { exact: true })).toHaveValue("smtp.t13.test");
    await expect(page.getByLabel("Port", { exact: true })).toHaveValue("2525");
    await expect(page.getByLabel("Security")).toHaveValue("ssl");
    await expect(page.getByLabel("From address")).toHaveValue("noreply@t13.test");
    await expect(page.getByTestId("password-state")).toHaveText("Password: not set");

    await page.getByLabel("Password", { exact: true }).fill("t13-not-a-real-password");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Email settings saved")).toBeVisible();
    await page.reload();
    await expect(page.getByTestId("password-state")).toHaveText("Password: set");
    // The stored password is never sent back to the page.
    await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");

    // Dry run only: no mail leaves the machine.
    await page.getByLabel("Dry run").check();
    await page.getByRole("button", { name: "Send test email" }).click();
    await expect(page.getByText("Dry run OK")).toBeVisible();
  } finally {
    if (ownId) {
      await page.request.delete(`/api/connectors/${ownId}`, {
        headers: { "X-CSRF-Token": await csrf(page) },
      });
    }
  }
});
