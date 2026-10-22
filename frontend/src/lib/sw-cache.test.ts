import { describe, expect, it } from "vitest";

import {
  AUDIO_CACHE,
  DEFAULT_CAP_BYTES,
  META_CACHE,
  cachesToDelete,
  loadCap,
  saveCap,
} from "./sw-cache";

class FakeCache {
  store = new Map<string, Response>();
  async put(req: string | Request, res: Response) {
    this.store.set(typeof req === "string" ? req : new URL(req.url).pathname, res);
  }
  async match(req: string | Request) {
    const r = this.store.get(typeof req === "string" ? req : new URL(req.url).pathname);
    return r?.clone();
  }
}

describe("cachesToDelete", () => {
  const prefix = "setvault-2";
  it("keeps the current version, the audio cache and the meta cache", () => {
    const keys = [`${prefix}-static`, `${prefix}-runtime`, AUDIO_CACHE, META_CACHE];
    expect(cachesToDelete(keys, prefix)).toEqual([]);
  });
  it("drops old versioned caches including legacy versioned audio", () => {
    const keys = ["setvault-1-static", "setvault-1-runtime", "setvault-1-audio", AUDIO_CACHE];
    expect(cachesToDelete(keys, prefix)).toEqual([
      "setvault-1-static",
      "setvault-1-runtime",
      "setvault-1-audio",
    ]);
  });
  it("names the audio cache without a version", () => {
    expect(AUDIO_CACHE).toBe("setvault-audio");
  });
});

describe("loadCap/saveCap", () => {
  it("defaults when nothing is stored", async () => {
    expect(await loadCap(new FakeCache() as unknown as Cache)).toBe(DEFAULT_CAP_BYTES);
  });
  it("round-trips a saved cap", async () => {
    const c = new FakeCache() as unknown as Cache;
    await saveCap(c, 1500);
    expect(await loadCap(c)).toBe(1500);
  });
  it("ignores garbage", async () => {
    const c = new FakeCache();
    await c.put("/__setvault/cap", new Response("nope"));
    expect(await loadCap(c as unknown as Cache)).toBe(DEFAULT_CAP_BYTES);
  });
});
