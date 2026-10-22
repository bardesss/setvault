import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers/auth";

/**
 * Audio cache cap eviction: prime the audio cache with three oversized fake
 * entries via the page-side `caches.open(...).put(...)` API, then lower the
 * SW's cap via the `set-cap` postMessage. The SW's message handler enforces
 * the new cap immediately (admin lowered it; the cache may already exceed),
 * which is the same path the settings UI takes. Asserts the oldest entry
 * is evicted.
 *
 * Locks the §J18 contract (admin-configurable cap, oldest-first eviction).
 */
test("audio cache evicts oldest entry when over cap", async ({
  page,
  request,
  context,
}) => {
  const seed = await loginAs(page, request);

  await page.goto(`/sets/${seed.set.slug}`, { waitUntil: "networkidle" });
  await page.waitForFunction(
    async () => {
      if (!("serviceWorker" in navigator)) return false;
      const reg = await navigator.serviceWorker.getRegistration();
      return !!reg?.active;
    },
    { timeout: 15_000 },
  );
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForFunction(
    () => navigator.serviceWorker?.controller !== null,
    { timeout: 15_000 },
  );

  const audioCacheName = await page.evaluate(async () => {
    const names = await caches.keys();
    return names.find((n) => n.endsWith("-audio")) ?? null;
  });
  expect(audioCacheName, "audio cache should be created by the SW").not.toBeNull();
  expect(audioCacheName, "audio cache is unversioned so deploys keep it").toBe(
    "setvault-audio",
  );

  // Prime the cache with three fake stream entries in known insertion order.
  await page.evaluate(async (name) => {
    const cache = await caches.open(name);
    for (const slug of ["fake-a", "fake-b", "fake-c"]) {
      const body = new Uint8Array(1000).fill(slug.charCodeAt(5));  // unique bytes
      await cache.put(
        new Request(`/api/sets/${slug}/stream`),
        new Response(body, {
          status: 200,
          headers: { "content-type": "audio/flac", "content-length": "1000" },
        }),
      );
    }
  }, audioCacheName!);

  const before = await page.evaluate(async (name) => {
    const cache = await caches.open(name);
    return (await cache.keys()).map((r) => new URL(r.url).pathname);
  }, audioCacheName!);
  expect(before).toEqual(expect.arrayContaining([
    "/api/sets/fake-a/stream",
    "/api/sets/fake-b/stream",
    "/api/sets/fake-c/stream",
  ]));

  // Lower the cap to 1500 bytes via a MessageChannel so we can await the
  // SW's enforcement completing.
  await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.getRegistration();
    await new Promise<void>((resolve) => {
      const channel = new MessageChannel();
      channel.port1.onmessage = (event) => {
        if (event.data?.type === "cap-enforced") resolve();
      };
      reg!.active!.postMessage(
        { type: "set-cap", bytes: 1500 },
        [channel.port2],
      );
      setTimeout(resolve, 8_000);  // fallback if no reply for some reason
    });
  });

  const after = await page.evaluate(async (name) => {
    const cache = await caches.open(name);
    return (await cache.keys()).map((r) => new URL(r.url).pathname);
  }, audioCacheName!);

  expect(after, "fake-a (oldest fake) should be evicted").not.toContain(
    "/api/sets/fake-a/stream",
  );

  // The cap is persisted inside the SW so a restart does not forget it.
  const persisted = await page.evaluate(async () => {
    const meta = await caches.open("setvault-meta");
    return (await meta.match("/__setvault/cap"))?.text() ?? null;
  });
  expect(persisted).toBe("1500");

  // Cleanup so the next test doesn't see the lowered cap or fake entries.
  await context.clearCookies();
});
