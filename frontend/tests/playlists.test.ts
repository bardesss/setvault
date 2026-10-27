import { devices, expect, test, type Page } from "@playwright/test";
import { createMember } from "./helpers/auth";

const ALPHA = "Alpha Night";
const BRAVO = "Bravo Session";
const miniTitle = (page: Page) => page.locator('[aria-label="now playing"] .m-sheet-title');

async function createPlaylistViaUi(page: Page, name: string): Promise<string> {
  await page.goto("/playlists");
  await page.getByPlaceholder("New playlist name").fill(name);
  await page.locator('[data-test="playlist-create"]').click();
  const link = page.getByRole("link", { name: new RegExp(name) });
  await expect(link).toBeVisible();
  return (await link.getAttribute("href"))!.split("/").pop()!;
}

async function addFromSetPage(page: Page, slug: string, playlist: string) {
  await page.goto(`/sets/${slug}`);
  await page.getByRole("button", { name: "Add to playlist" }).click();
  await page.getByRole("menuitemcheckbox", { name: playlist }).click();
  await expect(page.getByRole("menuitemcheckbox", { name: playlist })).toBeChecked();
  await page.keyboard.press("Escape");
}

const rowTitles = (page: Page) => page.locator(".set-row .set-title");

test("create, add from set page, reorder, rename, delete", async ({ page, request }) => {
  await createMember(page, request);
  const name = `Road trip ${crypto.randomUUID().slice(0, 8)}`;
  const id = await createPlaylistViaUi(page, name);

  await addFromSetPage(page, "e2e-alpha", name);
  await addFromSetPage(page, "e2e-bravo", name);

  await page.goto(`/playlists/${id}`);
  await expect(rowTitles(page)).toHaveText([ALPHA, BRAVO]);

  const put = page.waitForResponse((r) => r.request().method() === "PUT" && r.url().endsWith(`/items`));
  await page.getByRole("button", { name: `Move ${BRAVO} up` }).click();
  expect((await put).ok()).toBeTruthy();
  await expect(rowTitles(page)).toHaveText([BRAVO, ALPHA]);
  await page.reload();
  await expect(rowTitles(page)).toHaveText([BRAVO, ALPHA]);

  const renamed = `${name} renamed`;
  await page.getByRole("button", { name: "Rename" }).click();
  await page.getByRole("textbox", { name: "Rename" }).fill(renamed);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: renamed })).toBeVisible();

  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(page).toHaveURL(/\/playlists$/);
  await expect(page.getByRole("link", { name: new RegExp(name) })).toHaveCount(0);
});

test("adding twice keeps one row", async ({ page, request }) => {
  await createMember(page, request);
  const name = `Twice ${crypto.randomUUID().slice(0, 8)}`;
  const id = await createPlaylistViaUi(page, name);

  // Add through the API twice: the menu itself toggles, so a second click removes.
  const csrf = (await page.context().cookies()).find((c) => c.name === "csrf_token")?.value ?? "";
  for (let i = 0; i < 2; i++) {
    const r = await page.request.post(`/api/me/playlists/${id}/items`, {
      data: { slug: "e2e-alpha" },
      headers: { "X-CSRF-Token": csrf },
    });
    expect(r.status()).toBe(204);
  }
  await page.goto(`/playlists/${id}`);
  await expect(rowTitles(page)).toHaveText([ALPHA]);
  await page.goto("/playlists");
  await expect(page.getByRole("link", { name: new RegExp(name) })).toContainText("1 set");
});

test("another member cannot open my playlist", async ({ page, request, browser }) => {
  await createMember(page, request);
  const id = await createPlaylistViaUi(page, `Private ${crypto.randomUUID().slice(0, 8)}`);

  const other = await browser.newContext();
  try {
    const otherPage = await other.newPage();
    await createMember(otherPage, request);
    await otherPage.goto(`/playlists/${id}`);
    await expect(otherPage.getByText("Playlist not found.")).toBeVisible();
  } finally {
    await other.close();
  }
});

async function playAll(page: Page, request: Parameters<typeof createMember>[1]) {
  await createMember(page, request);
  // Created through the API: the shell is wider than a phone viewport (a known
  // layout issue), which puts the Create button out of reach of a tap.
  const csrf = (await page.context().cookies()).find((c) => c.name === "csrf_token")?.value ?? "";
  const created = await page.request.post("/api/me/playlists", {
    data: { name: `Queue ${crypto.randomUUID().slice(0, 8)}` },
    headers: { "X-CSRF-Token": csrf },
  });
  expect(created.status()).toBe(201);
  const { id } = (await created.json()) as { id: string };
  for (const slug of ["e2e-alpha", "e2e-bravo"]) {
    const r = await page.request.post(`/api/me/playlists/${id}/items`, {
      data: { slug },
      headers: { "X-CSRF-Token": csrf },
    });
    expect(r.status()).toBe(204);
  }
  await page.goto(`/playlists/${id}`);
  await expect(rowTitles(page)).toHaveText([ALPHA, BRAVO]);
  await page.locator('[data-test="playlist-play-all"]').click();
  await expect(miniTitle(page)).toHaveText(ALPHA);
}

test("visiting a set page does not hijack the queue", async ({ page, request }) => {
  await playAll(page, request);
  // Client-side navigation keeps the audio element (and the queue) alive.
  await page.locator('a[href="/sets"]').first().click();
  await page.locator('a[href="/sets/e2e-charlie"]').first().click();
  await expect(page.getByRole("heading", { name: /Charlie Closing/ })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect(miniTitle(page)).not.toHaveText("Charlie Closing");
  await expect(miniTitle(page)).toHaveText(/Alpha Night|Bravo Session/);
});

test.describe("mobile", () => {
  // defaultBrowserType can't be set inside a describe block.
  const { defaultBrowserType: _ignored, ...pixel } = devices["Pixel 7"];
  test.use({ ...pixel });

  test("mobile: ended advances to the next set", async ({ page, request }) => {
    await playAll(page, request);
    // Each seeded set is 1 s of silence.
    await expect(miniTitle(page)).toHaveText(BRAVO, { timeout: 10_000 });
    await expect(page.locator('[data-test="mini-play-state"]')).toHaveAttribute(
      "data-state",
      "paused",
      { timeout: 10_000 },
    );
  });
});
