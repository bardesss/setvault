import { expect, test, type Page } from "@playwright/test";
import { loginAs } from "./helpers/auth";

async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const c = (await page.context().cookies()).find((x) => x.name === "csrf_token");
  return c ? { "X-CSRF-Token": c.value } : {};
}

async function deleteMonitorsWhere(
  page: Page,
  match: (m: { id: string; query_text: string | null; external_id: string | null }) => boolean,
) {
  const request = page.request;
  const headers = await csrfHeaders(page);
  const res = await request.get("/api/monitors");
  if (!res.ok()) return;
  const { items } = await res.json();
  for (const m of items) {
    if (match(m)) await request.delete(`/api/monitors/${m.id}`, { headers });
  }
}

test("monitor button on an artist page toggles and persists", async ({ page }) => {
  await loginAs(page, page.request);
  const name = `E2E Monitor Artist ${Date.now()}`;
  const created = await page.request.post("/api/catalog/artists", {
    data: { name },
    headers: await csrfHeaders(page),
  });
  expect(created.ok()).toBeTruthy();
  const artist = await created.json();

  try {
    await page.goto(`/artists/${artist.slug}`, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Monitor", exact: true }).click();
    await expect(page.getByRole("button", { name: /Monitoring ✓/ })).toBeVisible();

    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByRole("button", { name: /Monitoring ✓/ })).toBeVisible();

    await page.getByRole("button", { name: /Monitoring ✓/ }).click();
    await expect(page.getByRole("button", { name: "Monitor", exact: true })).toBeVisible();
  } finally {
    await deleteMonitorsWhere(page, (m) => m.query_text === name);
  }
});

test("admin monitors: entity monitor form and inline cap edit", async ({ page }) => {
  await loginAs(page, page.request);
  const extId = `e2e-chan-${Date.now()}`;

  try {
    await page.goto("/admin/monitors", { waitUntil: "networkidle" });
    await page.getByLabel("Kind", { exact: true }).selectOption("entity");
    const source = page.getByLabel("Source", { exact: true });
    await source.selectOption({ index: 1 });
    await page.getByLabel("External id").fill(extId);
    await page.getByRole("button", { name: /add monitor/i }).click();

    const row = page.getByRole("row", { name: new RegExp(extId) });
    await expect(row).toBeVisible();

    const cap = row.getByLabel(/per-poll cap/i);
    await cap.fill("10");
    await cap.blur();
    await expect(cap).toHaveValue("10");

    await page.reload({ waitUntil: "networkidle" });
    await expect(
      page.getByRole("row", { name: new RegExp(extId) }).getByLabel(/per-poll cap/i),
    ).toHaveValue("10");
  } finally {
    await deleteMonitorsWhere(page, (m) => m.external_id === extId);
  }
});

test("admin monitors: add a query monitor", async ({ page }) => {
  await loginAs(page, page.request);
  const q = `E2E Query ${Date.now()}`;
  try {
    await page.goto("/admin/monitors", { waitUntil: "networkidle" });
    await page.getByPlaceholder(/artist, party, or venue/i).fill(q);
    await page.getByRole("button", { name: /add monitor/i }).click();
    await expect(page.getByRole("row", { name: new RegExp(q) })).toBeVisible();
  } finally {
    await deleteMonitorsWhere(page, (m) => m.query_text === q);
  }
});

test("nav shows Discoveries and the page has status tabs", async ({ page }) => {
  await loginAs(page, page.request);
  await page.goto("/", { waitUntil: "networkidle" });
  await expect(page.getByRole("link", { name: /^Discoveries/ })).toBeVisible();

  await page.goto("/discoveries", { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: /discoveries/i })).toBeVisible();
  for (const label of ["Pending", "Ingested", "Dismissed", "All"]) {
    await expect(page.getByRole("tab", { name: new RegExp(`^${label}`) })).toBeVisible();
  }
  await expect(page.getByRole("tab", { name: /^Pending/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  await page.getByRole("tab", { name: /^All/ }).click();
  await expect(page).toHaveURL(/status=all/);
});
