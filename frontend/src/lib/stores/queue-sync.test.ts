import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { get } from "svelte/store";

const getQueue = vi.fn();
const putQueue = vi.fn();
const getSet = vi.fn();
const playQueue = vi.fn(async () => undefined);
let listener: ((q: { slugs: string[]; index: number }) => void) | null = null;

vi.mock("#lib/api/queue.ts", () => ({
  getQueue: () => getQueue(),
  putQueue: (b: unknown) => putQueue(b),
}));
vi.mock("#lib/api/sets.ts", () => ({ getSet: (s: string) => getSet(s) }));
vi.mock("./audio", async () => {
  const { writable } = await import("svelte/store");
  return {
    queue: writable({ slugs: [], index: 0 }),
    player: writable({ playing: false, position: 0, set: null }),
    onQueueChange: (fn: typeof listener) => { listener = fn; },
    playQueue: (...a: unknown[]) => (playQueue as (...x: unknown[]) => Promise<void>)(...a),
  };
});

const KEY = "setvault.playQueue";
const T1 = "2026-10-27T10:00:00.123456+00:00";
const T2 = "2026-10-27T11:00:00.654321+00:00";

async function mod() {
  const sync = await import("./queue-sync");
  const audio = await import("./audio");
  // The mocked module's stores can outlive resetModules: start each test clean.
  audio.queue.set({ slugs: [], index: 0 });
  audio.player.set({ playing: false, position: 0, set: null } as never);
  return { sync, audio };
}

async function flush() { await vi.advanceTimersByTimeAsync(0); }

function memoryStorage() {
  const m = new Map<string, string>();
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => { m.set(k, String(v)); },
    removeItem: (k: string) => { m.delete(k); },
    clear: () => m.clear(),
  };
}

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  vi.stubGlobal("localStorage", memoryStorage());
  vi.stubGlobal("window", {});
  const doc = new EventTarget() as EventTarget & { visibilityState: string };
  doc.visibilityState = "visible";
  vi.stubGlobal("document", doc);
  listener = null;
  getQueue.mockReset().mockResolvedValue({ slugs: [], index: 0, updated_at: null });
  putQueue.mockReset().mockResolvedValue({ updated_at: T1, overwrote_newer: false });
  getSet.mockReset().mockResolvedValue({ slug: "b", title: "Set B" });
  playQueue.mockClear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("queue sync", () => {
  it("queue change saves locally and PUTs once after debounce", async () => {
    const { sync, audio } = await mod();
    sync.startQueueSync();
    await flush();
    audio.queue.set({ slugs: ["a", "b"], index: 1 });
    listener!({ slugs: ["a", "b"], index: 1 });
    listener!({ slugs: ["a", "b"], index: 1 });
    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ slugs: ["a", "b"], index: 1 });
    await vi.advanceTimersByTimeAsync(499);
    expect(putQueue).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2);
    expect(putQueue).toHaveBeenCalledTimes(1);
    expect(putQueue).toHaveBeenCalledWith({ slugs: ["a", "b"], index: 1, base_updated_at: null });
    expect(JSON.parse(localStorage.getItem(KEY)!).updatedAt).toBe(T1);
    // Next PUT echoes the server string untouched.
    listener!({ slugs: ["a", "b"], index: 0 });
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenLastCalledWith({ slugs: ["a", "b"], index: 0, base_updated_at: T1 });
  });

  it("position-only updates do not PUT", async () => {
    const { sync, audio } = await mod();
    sync.startQueueSync();
    await flush();
    audio.player.update((s) => ({ ...s, position: 42 }));
    await vi.advanceTimersByTimeAsync(2000);
    expect(putQueue).not.toHaveBeenCalled();
  });

  it("newer server queue sets resumeOffer without playing", async () => {
    getQueue.mockResolvedValue({ slugs: ["a", "b"], index: 1, updated_at: T2 });
    const { sync } = await mod();
    sync.startQueueSync();
    await flush();
    expect(getSet).toHaveBeenCalledWith("b");
    expect(get(sync.resumeOffer)).toEqual({ slugs: ["a", "b"], index: 1, title: "Set B" });
    expect(playQueue).not.toHaveBeenCalled();
    expect(JSON.parse(localStorage.getItem(KEY)!).updatedAt).toBe(T2);
  });

  it("older server queue is ignored", async () => {
    localStorage.setItem(KEY, JSON.stringify({ slugs: ["x"], index: 0, updatedAt: T2 }));
    getQueue.mockResolvedValue({ slugs: ["a", "b"], index: 1, updated_at: T1 });
    const { sync, audio } = await mod();
    sync.startQueueSync();
    await flush();
    expect(get(sync.resumeOffer)).toBeNull();
    expect(get(audio.queue).slugs).toEqual(["x"]); // local copy loaded, not playing
    expect(playQueue).not.toHaveBeenCalled();
  });

  it("no offer while playing", async () => {
    getQueue.mockResolvedValue({ slugs: ["a", "b"], index: 0, updated_at: T2 });
    const { sync, audio } = await mod();
    audio.player.update((s) => ({ ...s, playing: true }));
    sync.startQueueSync();
    await flush();
    expect(get(sync.resumeOffer)).toBeNull();
    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ slugs: ["a", "b"], updatedAt: T2 });
  });

  it("visibilitychange to visible refetches", async () => {
    const { sync } = await mod();
    sync.startQueueSync();
    await flush();
    expect(getQueue).toHaveBeenCalledTimes(1);
    (document as unknown as { visibilityState: string }).visibilityState = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
    await flush();
    expect(getQueue).toHaveBeenCalledTimes(1);
    (document as unknown as { visibilityState: string }).visibilityState = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    await flush();
    expect(getQueue).toHaveBeenCalledTimes(2);
  });

  it("acceptOffer plays at the offered index", async () => {
    getQueue.mockResolvedValue({ slugs: ["a", "b"], index: 1, updated_at: T2 });
    const { sync } = await mod();
    sync.startQueueSync();
    await flush();
    await sync.acceptOffer();
    expect(playQueue).toHaveBeenCalledWith(["a", "b"], 1);
    expect(get(sync.resumeOffer)).toBeNull();
  });

  it("localStorage throwing does not break sync", async () => {
    const deny = () => { throw new Error("denied"); };
    vi.stubGlobal("localStorage", { getItem: deny, setItem: deny });
    const { sync } = await mod();
    expect(() => sync.startQueueSync()).not.toThrow();
    await flush();
    expect(() => listener!({ slugs: ["a"], index: 0 })).not.toThrow();
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenCalledTimes(1);
  });

  it("playSingle with an empty local queue still PUTs the empty queue", async () => {
    const { sync } = await mod();
    sync.startQueueSync();
    await flush();
    listener!({ slugs: [], index: 0 });
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenCalledWith({ slugs: [], index: 0, base_updated_at: null });
  });

  it("overwrote_newer schedules one refetch", async () => {
    putQueue.mockResolvedValue({ updated_at: T1, overwrote_newer: true });
    const { sync } = await mod();
    sync.startQueueSync();
    await flush();
    listener!({ slugs: ["a"], index: 0 });
    await vi.advanceTimersByTimeAsync(600);
    expect(getQueue).toHaveBeenCalledTimes(2);
  });
});
