import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

test("set detail renders title + waveform region", async ({ page, request }) => {
  await loginAs(page, request);
  await page.goto("/sets/seeded-set");
  await expect(page.getByRole("heading", { name: /seeded set/i })).toBeVisible();
  await expect(page.locator("[data-test=wavesurfer-canvas] canvas")).toBeVisible();
});

test("space toggles playback", async ({ page, request }) => {
  await loginAs(page, request);
  await page.goto("/sets/seeded-set");
  await page.locator("[data-test=wavesurfer-canvas] canvas").click();
  await page.keyboard.press("Space");
  await expect(page.locator("[data-test=play-state]")).toHaveAttribute("data-state", "playing");
});

test("waveform is drawn from precomputed peaks without fetching the stream", async ({ page, request }) => {
  await loginAs(page, request);
  const streams: string[] = [];
  page.on("request", (r) => { // The shared <audio> element loads metadata itself (resource type "media");
    // wavesurfer decoding would fetch() the whole stream.
    if (/\/api\/sets\/seeded-set\/stream/.test(r.url()) && r.resourceType() !== "media") streams.push(r.url()); });
  const peaksReq = page.waitForRequest(/\/api\/sets\/seeded-set\/waveform/);
  await page.goto("/sets/seeded-set");
  await peaksReq;
  await expect(page.locator("[data-test=wavesurfer-canvas] canvas").first()).toBeVisible();
  // tagCanvas runs before `ready`, so a visible canvas alone proves nothing
  await expect(page.locator(".wave[data-ready=true]")).toBeVisible();
  await page.locator("[data-test=wavesurfer-canvas] canvas").first().click();
  expect(streams).toEqual([]);
});

test("waveform falls back to decoding the stream when peaks are invalid", async ({ page, request }) => {
  await loginAs(page, request);
  await page.route(/\/api\/sets\/seeded-set\/waveform/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.goto("/sets/seeded-set");
  await expect(page.locator("[data-test=wavesurfer-canvas] canvas").first()).toBeVisible();
  await expect(page.locator(".wave[data-ready=true]")).toBeVisible();
});
