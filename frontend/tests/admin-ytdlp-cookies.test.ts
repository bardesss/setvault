import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

// SW caches /api GETs; block so route stubs apply.
test.use({ serviceWorkers: "block" });

const COOKIES =
  "# Netscape HTTP Cookie File\n" +
  ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tabc\n" +
  ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tHSID\tdef\n";

test("sources tab: upload, replace and remove YouTube cookies", async ({ page, request }) => {
  await loginAs(page, request);

  // The cookie file lives in the server's config volume, shared by every
  // spec: stub the API instead of touching it.
  let status = { set: false, uploaded_at: null as string | null, youtube_cookies: 0 };
  const bodies: string[] = [];
  let deletes = 0;
  await page.route(/\/api\/admin\/ytdlp-cookies$/, async (route) => {
    const req = route.request();
    if (req.method() === "PUT") {
      const body = req.postData() ?? "";
      bodies.push(body);
      if (!body.includes("youtube.com")) {
        return route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ detail: "no youtube.com cookies found" }),
        });
      }
      status = {
        set: true,
        uploaded_at: "2026-10-25T12:00:00+00:00",
        youtube_cookies: body.split("\n").filter((l) => l.startsWith(".youtube.com")).length,
      };
    } else if (req.method() === "DELETE") {
      deletes += 1;
      status = { set: false, uploaded_at: null, youtube_cookies: 0 };
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(status),
    });
  });

  await page.goto("/admin/sources");
  await expect(page.getByRole("heading", { name: "YouTube cookies" })).toBeVisible();
  await expect(page.getByTestId("cookies-status")).toHaveText("No cookies set.");
  await expect(page.getByRole("button", { name: "Remove" })).toHaveCount(0);

  // Upload.
  const file = page.getByTestId("cookies-file");
  await file.setInputFiles({ name: "cookies.txt", mimeType: "text/plain", buffer: Buffer.from(COOKIES) });
  await expect(page.getByTestId("cookies-status")).toContainText("2 YouTube cookies");
  expect(bodies).toEqual([COOKIES]);

  // A rejected replacement shows the server's reason and keeps the status.
  await file.setInputFiles({ name: "junk.txt", mimeType: "text/plain", buffer: Buffer.from("junk") });
  await expect(page.getByRole("alert")).toHaveText("no youtube.com cookies found");
  await expect(page.getByTestId("cookies-status")).toContainText("2 YouTube cookies");
  await expect(page.getByRole("button", { name: "Replace" })).toBeVisible();

  // Remove asks first; cancel keeps them.
  await page.getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
  expect(deletes).toBe(0);

  await page.getByRole("button", { name: "Remove" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
  await expect(page.getByTestId("cookies-status")).toHaveText("No cookies set.");
  expect(deletes).toBe(1);
});
