import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// "edit-target" is seeded for this file alone (dev_seed.py: EDIT_SET_SLUG):
// one artist (E2E Resident), venue E2E Club. Tests here put it back to that
// state first, so reruns against the same database start clean.
const SLUG = "edit-target";
const TITLE = "Edit Target";
const TAG = "e2e-edited";

// The service worker answers /api GETs; keep it out so the page sees fresh data.
test.use({ serviceWorkers: "block" });

async function lookupId(page: Page, kind: string, q: string, slug: string): Promise<string> {
  const res = await page.request.get(`/api/catalog/lookup?kind=${kind}&q=${encodeURIComponent(q)}`);
  expect(res.ok()).toBeTruthy();
  const row = ((await res.json()) as { id: string; slug: string }[]).find((r) => r.slug === slug);
  if (!row) throw new Error(`seeded ${kind} ${slug} not found`);
  return row.id;
}

async function resetSet(page: Page): Promise<void> {
  const csrf = (await page.context().cookies()).find((c) => c.name === "csrf_token")?.value ?? "";
  const res = await page.request.patch(`/api/sets/${SLUG}`, {
    headers: { "X-CSRF-Token": csrf },
    data: {
      title: TITLE,
      artists: [{ id: await lookupId(page, "artist", "E2E Resident", "e2e-resident"), role: "main" }],
      venue_id: await lookupId(page, "venue", "E2E Club", "e2e-club"),
      party_id: null,
      date: null,
      description: null,
      tag_names: [],
    },
  });
  expect(res.ok()).toBeTruthy();
}

async function openEditor(page: Page): Promise<void> {
  await page.goto(`/sets/${SLUG}`);
  await page.getByRole("link", { name: "Edit", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/sets/${SLUG}/edit$`));
  await expect(page.getByRole("heading", { name: "Edit set" })).toBeVisible();
}

test.describe("set metadata editor", () => {
  test.beforeEach(async ({ page, request }) => {
    await loginAs(page, request);
    await resetSet(page);
  });

  test("edits title, artists with roles, tags and venue", async ({ page }) => {
    const guest = `Guest ${Date.now()}`;
    const newTitle = `Edited Target ${Date.now()}`;
    await openEditor(page);

    await page.getByLabel("Title", { exact: true }).fill(newTitle);

    const artists = page.getByRole("group", { name: "Artists" });
    await artists.getByRole("combobox", { name: "Add an artist…" }).fill(guest);
    await artists.getByRole("option", { name: `Create "${guest}"` }).click();
    await expect(artists.getByText(guest, { exact: true })).toBeVisible();
    await artists.getByLabel(`Role for ${guest}`).selectOption("b2b");

    const tags = page.getByRole("group", { name: "Tags" });
    await tags.getByRole("combobox", { name: "Add a tag…" }).fill(TAG);
    // Either the existing tag (earlier runs) or the "Create" row is highlighted first.
    await expect(tags.locator("[role=option][aria-selected=true]")).toBeVisible();
    await tags.getByRole("combobox", { name: "Add a tag…" }).press("Enter");
    await expect(tags.getByText(TAG, { exact: true })).toBeVisible();

    const venue = page.getByRole("group", { name: "Venue" });
    await venue.getByRole("button", { name: "Clear" }).click();
    await expect(venue.getByText("E2E Club")).toHaveCount(0);

    await page.getByRole("button", { name: "Save" }).click();

    await expect(page).toHaveURL(new RegExp(`/sets/${SLUG}$`));
    await expect(page.getByRole("status").filter({ hasText: "Set saved" })).toBeVisible();
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toContainText(newTitle);
    await expect(heading).toContainText(`E2E Resident, ${guest}`);
    await expect(page.locator(".set-tags .tag-pill", { hasText: TAG })).toBeVisible();
    await expect(page.locator('.set-meta a[href^="/venues/"]')).toHaveCount(0);

    const saved = await (await page.request.get(`/api/sets/${SLUG}`)).json();
    expect(saved.artists.map((a: { name: string; role: string }) => [a.name, a.role])).toEqual([
      ["E2E Resident", "main"],
      [guest, "b2b"],
    ]);
    expect(saved.venue).toBeNull();
  });

  test("asks before leaving with unsaved changes", async ({ page }) => {
    await openEditor(page);
    await page.getByLabel("Title", { exact: true }).fill("Not saved");

    await page.getByRole("link", { name: "Cancel" }).click();
    const dialog = page.getByRole("dialog", { name: "Discard changes?" });
    await expect(dialog).toBeVisible();

    // Stay: the edit is kept.
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(new RegExp(`/sets/${SLUG}/edit$`));
    await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Not saved");

    // Leave: the set is unchanged.
    await page.getByRole("link", { name: "Cancel" }).click();
    await dialog.getByRole("button", { name: "Discard" }).click();
    await expect(page).toHaveURL(new RegExp(`/sets/${SLUG}$`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(TITLE);
  });
});
