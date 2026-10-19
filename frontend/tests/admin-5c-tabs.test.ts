import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

const tabs: { href: string; expectedHeading: RegExp }[] = [
  { href: "/admin/recycle", expectedHeading: /Recycle bin/i },
  { href: "/admin/tasks", expectedHeading: /Scheduled tasks/i },
  { href: "/admin/health", expectedHeading: /^Health$/i },
  { href: "/admin/webhooks", expectedHeading: /Library refresh webhooks/i },
  { href: "/admin/watch-folders", expectedHeading: /Watch folders/i },
  { href: "/admin/unmatched", expectedHeading: /Unmatched inbox/i },
  { href: "/admin/duplicates", expectedHeading: /^Duplicates$/i },
  { href: "/admin/quality", expectedHeading: /^Quality$/i },
  { href: "/admin/wanted", expectedHeading: /^Wanted$/i },
];

for (const tab of tabs) {
  test(`admin tab ${tab.href} loads`, async ({ page, request }) => {
    await loginAs(page, request);
    await page.goto(tab.href, { waitUntil: "networkidle" });
    await expect(page.locator("h2")).toContainText(tab.expectedHeading);
  });
}
