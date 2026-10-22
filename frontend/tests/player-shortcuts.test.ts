import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

for (const startPlaying of [false, true]) {
  test(`ctrl+k opens search without toggling playback (${startPlaying ? "playing" : "paused"})`, async ({ page, request }) => {
    const seed = await loginAs(page, request);
    await page.goto(`/sets/${seed.set.slug}`, { waitUntil: "networkidle" });
    const state = page.locator('[data-test="play-state"]');
    await state.waitFor({ state: "visible", timeout: 10_000 });
    if (startPlaying) {
      await state.click();
      await expect(state).toHaveAttribute("data-state", "playing", { timeout: 15_000 });
    }
    await page.locator("body").click({ position: { x: 1, y: 1 } });
    await page.keyboard.press("Control+K");
    await page.waitForURL("**/search");

    const mini = page.locator('[data-test="mini-play-state"]');
    if (startPlaying) {
      await expect(mini).toHaveAttribute("data-state", "playing");
      await page.waitForTimeout(500);
      await expect(mini).toHaveAttribute("data-state", "playing");
    } else {
      await page.waitForTimeout(500);
      // never started: the mini-player is absent or, if mounted, not playing
      expect(await mini.getAttribute("data-state").catch(() => null)).not.toBe("playing");
    }
  });
}
