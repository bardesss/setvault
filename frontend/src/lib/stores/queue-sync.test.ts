import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { get } from "svelte/store";

const getQueue = vi.fn();
const putQueue = vi.fn();
const getSet = vi.fn();
const pause = vi.fn();
const resetQueue = vi.fn();
const reset = vi.fn();
let listener: ((q: { slugs: string[]; index: number }) => void) | null = null;
const playQueue = vi.fn(async (slugs: string[], index: number) => {
  const { queue } = await import("./audio");
  queue.set({ slugs, index });
  listener?.({ slugs, index });
});

vi.mock("#lib/api/queue.ts", () => ({
  getQueue: () => getQueue(),
  putQueue: (b: unknown, init?: unknown) => putQueue(b, init),
}));
vi.mock("#lib/api/sets.ts", () => ({ getSet: (s: string) => getSet(s) }));
// Registered per test (doMock in beforeEach): player.subscribe listeners from an
// earlier test's module instance must not survive into the next one.
const audioFactory = async () => {
  const { writable } = await import("svelte/store");
  const queue = writable({ slugs: [], index: 0 });
  const player = writable<{ playing: boolean; position: number; set: unknown }>({ playing: false, position: 0, set: null });
  return {
    queue,
    player,
    onQueueChange: (fn: typeof listener) => { listener = fn; },
    pause: () => pause(),
    reset: () => { reset(); player.set({ playing: false, position: 0, set: null }); },
    resetQueue: () => { queue.set({ slugs: [], index: 0 }); resetQueue(); },
    playQueue: (s: string[], i: number) => playQueue(s, i),
  };
};

const KEY = "setvault.playQueue";
const T1 = "2026-10-27T10:00:00.123456+00:00";
const T2 = "2026-10-27T11:00:00.654321+00:00";
const USER = { id: "u1", email: "a@b.c", username: "a", display_name: "A", role: "user" } as never;

type Q = { slugs: string[]; index: number };

async function mod() {
  const sync = await import("./queue-sync");
  const audio = await import("./audio");
  const { session } = await import("./session");
  // The mocked module's stores can outlive resetModules: start each test clean.
  audio.queue.set({ slugs: [], index: 0 });
  audio.player.set({ playing: false, position: 0, set: null } as never);
  return { sync, audio, session };
}

/** Sign in, start sync, let the startup fetch settle. */
async function boot() {
  const m = await mod();
  m.session.set(USER);
  m.sync.startQueueSync();
  await flush();
  return m;
}

/** What audio.ts does: the queue store changes, then the listener is told. */
function change(audio: { queue: { set: (q: Q) => void } }, q: Q) {
  audio.queue.set(q);
  listener!(q);
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

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

let win: EventTarget;
let doc: EventTarget & { visibilityState: string };

beforeEach(() => {
  vi.resetModules();
  vi.doMock("./audio", audioFactory);
  vi.useFakeTimers();
  vi.stubGlobal("localStorage", memoryStorage());
  win = new EventTarget();
  vi.stubGlobal("window", win);
  doc = Object.assign(new EventTarget(), { visibilityState: "visible" });
  vi.stubGlobal("document", doc);
  listener = null;
  getQueue.mockReset().mockResolvedValue({ slugs: [], index: 0, updated_at: null });
  putQueue.mockReset().mockResolvedValue({ updated_at: T1, overwrote_newer: false });
  getSet.mockReset().mockImplementation(async (slug: string) => ({ slug, title: `Set ${slug}` }));
  playQueue.mockClear();
  pause.mockReset();
  reset.mockReset();
  resetQueue.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("queue sync: saving", () => {
  it("queue change saves locally and PUTs once after debounce", async () => {
    const { audio } = await boot();
    change(audio, { slugs: ["a", "b"], index: 1 });
    change(audio, { slugs: ["a", "b"], index: 1 });
    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ slugs: ["a", "b"], index: 1 });
    await vi.advanceTimersByTimeAsync(499);
    expect(putQueue).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2);
    expect(putQueue).toHaveBeenCalledTimes(1);
    expect(putQueue).toHaveBeenCalledWith({ slugs: ["a", "b"], index: 1, base_updated_at: null }, undefined);
    expect(JSON.parse(localStorage.getItem(KEY)!).updatedAt).toBe(T1);
    // Next PUT echoes the server string untouched.
    change(audio, { slugs: ["a", "b"], index: 0 });
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenLastCalledWith({ slugs: ["a", "b"], index: 0, base_updated_at: T1 }, undefined);
  });

  it("position-only updates do not PUT", async () => {
    const { audio } = await boot();
    audio.player.update((s) => ({ ...s, position: 42 }));
    await vi.advanceTimersByTimeAsync(2000);
    expect(putQueue).not.toHaveBeenCalled();
  });

  it("an emptied queue still PUTs the empty queue", async () => {
    const { audio } = await boot();
    change(audio, { slugs: [], index: 0 });
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenCalledWith({ slugs: [], index: 0, base_updated_at: null }, undefined);
  });

  it("overwrote_newer schedules one refetch", async () => {
    putQueue.mockResolvedValue({ updated_at: T1, overwrote_newer: true });
    const { audio } = await boot();
    expect(getQueue).toHaveBeenCalledTimes(1);
    change(audio, { slugs: ["a"], index: 0 });
    await vi.advanceTimersByTimeAsync(600);
    expect(getQueue).toHaveBeenCalledTimes(2);
  });

  it("localStorage throwing does not break sync", async () => {
    const deny = () => { throw new Error("denied"); };
    vi.stubGlobal("localStorage", { getItem: deny, setItem: deny, removeItem: deny });
    const { audio } = await boot();
    expect(() => change(audio, { slugs: ["a"], index: 0 })).not.toThrow();
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenCalledTimes(1);
  });

  it("corrupt JSON in the local copy is ignored", async () => {
    localStorage.setItem(KEY, "{not json");
    const { sync } = await boot();
    expect(get(sync.resumeOffer)).toBeNull();
    expect(getQueue).toHaveBeenCalledTimes(1);
  });

  it("pagehide flushes a pending PUT with keepalive", async () => {
    const { audio } = await boot();
    change(audio, { slugs: ["a", "b"], index: 1 });
    win.dispatchEvent(new Event("pagehide"));
    expect(putQueue).toHaveBeenCalledTimes(1);
    expect(putQueue).toHaveBeenCalledWith({ slugs: ["a", "b"], index: 1, base_updated_at: null }, { keepalive: true });
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenCalledTimes(1);
  });

  it("pagehide with nothing pending does not PUT", async () => {
    await boot();
    win.dispatchEvent(new Event("pagehide"));
    expect(putQueue).not.toHaveBeenCalled();
  });
});

describe("queue sync: offers", () => {
  it("newer server queue sets resumeOffer without playing or loading the queue", async () => {
    getQueue.mockResolvedValue({ slugs: ["a", "b"], index: 1, updated_at: T2 });
    const { sync, audio } = await boot();
    expect(getSet).toHaveBeenCalledWith("b");
    expect(get(sync.resumeOffer)).toEqual({ slugs: ["a", "b"], index: 1, title: "Set b" });
    expect(playQueue).not.toHaveBeenCalled();
    expect(get(audio.queue).slugs).toEqual([]);
    expect(JSON.parse(localStorage.getItem(KEY)!).updatedAt).toBe(T2);
  });

  it("a local copy is offered at startup but never loaded into the queue", async () => {
    localStorage.setItem(KEY, JSON.stringify({ userId: "u1", slugs: ["x", "y"], index: 1, updatedAt: T2 }));
    getQueue.mockResolvedValue({ slugs: ["x", "y"], index: 1, updated_at: T2 });
    const { sync, audio } = await boot();
    expect(get(sync.resumeOffer)).toEqual({ slugs: ["x", "y"], index: 1, title: "Set y" });
    expect(get(audio.queue).slugs).toEqual([]);
  });

  it("older server queue is ignored", async () => {
    localStorage.setItem(KEY, JSON.stringify({ userId: "u1", slugs: ["x"], index: 0, updatedAt: T2 }));
    getQueue.mockResolvedValue({ slugs: ["a", "b"], index: 1, updated_at: T1 });
    const { sync } = await boot();
    expect(get(sync.resumeOffer)).toEqual({ slugs: ["x"], index: 0, title: "Set x" });
    expect(playQueue).not.toHaveBeenCalled();
  });

  it("no offer while playing", async () => {
    getQueue.mockResolvedValue({ slugs: ["a", "b"], index: 0, updated_at: T2 });
    const m = await mod();
    m.audio.player.update((s) => ({ ...s, playing: true }));
    m.session.set(USER);
    m.sync.startQueueSync();
    await flush();
    expect(get(m.sync.resumeOffer)).toBeNull();
    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ slugs: ["a", "b"], updatedAt: T2 });
  });

  it("playback starting clears the offer", async () => {
    getQueue.mockResolvedValue({ slugs: ["a"], index: 0, updated_at: T2 });
    const { sync, audio } = await boot();
    expect(get(sync.resumeOffer)).not.toBeNull();
    audio.player.update((s) => ({ ...s, playing: true }));
    expect(get(sync.resumeOffer)).toBeNull();
  });

  it("a queue change clears a pending offer", async () => {
    getQueue.mockResolvedValue({ slugs: ["a"], index: 0, updated_at: T2 });
    const { sync, audio } = await boot();
    expect(get(sync.resumeOffer)).not.toBeNull();
    change(audio, { slugs: ["z"], index: 0 });
    expect(get(sync.resumeOffer)).toBeNull();
  });

  it("visibilitychange to visible refetches and offers only a newer server copy", async () => {
    localStorage.setItem(KEY, JSON.stringify({ userId: "u1", slugs: ["x"], index: 0, updatedAt: T1 }));
    getQueue.mockResolvedValue({ slugs: ["x"], index: 0, updated_at: T1 });
    const { sync } = await boot();
    sync.dismissOffer();
    expect(getQueue).toHaveBeenCalledTimes(1);
    doc.visibilityState = "hidden";
    doc.dispatchEvent(new Event("visibilitychange"));
    await flush();
    expect(getQueue).toHaveBeenCalledTimes(1);
    doc.visibilityState = "visible";
    doc.dispatchEvent(new Event("visibilitychange"));
    await flush();
    expect(getQueue).toHaveBeenCalledTimes(2);
    expect(get(sync.resumeOffer)).toBeNull(); // same copy: no offer on visibility
    getQueue.mockResolvedValue({ slugs: ["q"], index: 0, updated_at: T2 });
    doc.dispatchEvent(new Event("visibilitychange"));
    await flush();
    expect(get(sync.resumeOffer)?.slugs).toEqual(["q"]);
  });

  it("a newer but empty server queue is mirrored locally and drops the offer", async () => {
    localStorage.setItem(KEY, JSON.stringify({ userId: "u1", slugs: ["x"], index: 0, updatedAt: T1 }));
    getQueue.mockResolvedValue({ slugs: ["x"], index: 0, updated_at: T1 });
    const { sync } = await boot();
    expect(get(sync.resumeOffer)).not.toBeNull();
    getQueue.mockResolvedValue({ slugs: [], index: 0, updated_at: T2 });
    doc.dispatchEvent(new Event("visibilitychange"));
    await flush();
    expect(get(sync.resumeOffer)).toBeNull();
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual({ userId: "u1", slugs: [], index: 0, updatedAt: T2 });
  });

  it("acceptOffer plays at the offered index and PUTs exactly once", async () => {
    getQueue.mockResolvedValue({ slugs: ["a", "b"], index: 1, updated_at: T2 });
    const { sync } = await boot();
    await sync.acceptOffer();
    expect(playQueue).toHaveBeenCalledWith(["a", "b"], 1);
    expect(get(sync.resumeOffer)).toBeNull();
    await vi.advanceTimersByTimeAsync(5000);
    expect(putQueue).toHaveBeenCalledTimes(1);
    expect(getQueue).toHaveBeenCalledTimes(1);
  });
});

describe("queue sync: races", () => {
  it("after a PUT, local mirrors the body that was sent", async () => {
    const { audio, sync } = await boot();
    change(audio, { slugs: ["a"], index: 0 });
    audio.queue.set({ slugs: ["a", "b"], index: 1 }); // live queue moved on, no listener call
    await vi.advanceTimersByTimeAsync(600);
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual({ userId: "u1", slugs: ["a", "b"], index: 1, updatedAt: T1 });
    void sync;
  });

  it("a keepalive PUT response updates the base for the next PUT", async () => {
    const { audio } = await boot();
    change(audio, { slugs: ["a"], index: 0 });
    win.dispatchEvent(new Event("pagehide"));
    await flush();
    expect(JSON.parse(localStorage.getItem(KEY)!).updatedAt).toBe(T1);
    change(audio, { slugs: ["a", "b"], index: 0 });
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenLastCalledWith({ slugs: ["a", "b"], index: 0, base_updated_at: T1 }, undefined);
  });

  it("a failing keepalive PUT is swallowed", async () => {
    const { audio } = await boot();
    change(audio, { slugs: ["a"], index: 0 });
    putQueue.mockRejectedValue(new Error("gone"));
    win.dispatchEvent(new Event("pagehide"));
    await flush();
    expect(putQueue).toHaveBeenCalledTimes(1);
  });

  it("a fetch in flight cannot clobber a fresh local change", async () => {
    const d = deferred<{ slugs: string[]; index: number; updated_at: string }>();
    getQueue.mockReturnValue(d.promise);
    const m = await mod();
    m.session.set(USER);
    m.sync.startQueueSync();
    await flush();
    change(m.audio, { slugs: ["mine"], index: 0 });
    d.resolve({ slugs: ["theirs"], index: 0, updated_at: T2 });
    await flush();
    expect(get(m.sync.resumeOffer)).toBeNull();
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenCalledWith({ slugs: ["mine"], index: 0, base_updated_at: null }, undefined);
    expect(JSON.parse(localStorage.getItem(KEY)!).slugs).toEqual(["mine"]);
  });

  it("the PUT carries the live queue even if local is stale", async () => {
    const { audio } = await boot();
    change(audio, { slugs: ["a"], index: 0 });
    audio.queue.set({ slugs: ["a", "b"], index: 1 }); // changed without a listener call yet
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenCalledWith({ slugs: ["a", "b"], index: 1, base_updated_at: null }, undefined);
  });
});

describe("queue sync: auth", () => {
  it("discards a copy stored by another user", async () => {
    localStorage.setItem(KEY, JSON.stringify({ userId: "other", slugs: ["theirs"], index: 0, updatedAt: T2 }));
    getQueue.mockResolvedValue({ slugs: [], index: 0, updated_at: null });
    const m = await mod();
    m.sync.startQueueSync();
    m.session.set(USER);
    await flush();
    expect(get(m.sync.resumeOffer)).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
    change(m.audio, { slugs: ["mine"], index: 0 });
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenCalledWith({ slugs: ["mine"], index: 0, base_updated_at: null }, undefined);
  });

  it("discards a legacy copy without a userId", async () => {
    localStorage.setItem(KEY, JSON.stringify({ slugs: ["old"], index: 0, updatedAt: T2 }));
    const m = await boot();
    expect(get(m.sync.resumeOffer)).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("ignores queue changes while logged out", async () => {
    const m = await mod();
    m.sync.startQueueSync();
    change(m.audio, { slugs: ["a"], index: 0 });
    await vi.advanceTimersByTimeAsync(2000);
    expect(putQueue).not.toHaveBeenCalled();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("logout resets the queue (stopping an advance) and resets the player", async () => {
    const m = await boot();
    m.session.set(null);
    expect(resetQueue).toHaveBeenCalledTimes(1);
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("does not fetch while logged out", async () => {
    const m = await mod();
    m.sync.startQueueSync();
    doc.dispatchEvent(new Event("visibilitychange"));
    await flush();
    expect(getQueue).not.toHaveBeenCalled();
  });

  it("fetches when the session appears (client-side login)", async () => {
    const m = await mod();
    m.sync.startQueueSync();
    await flush();
    expect(getQueue).not.toHaveBeenCalled();
    getQueue.mockResolvedValue({ slugs: ["a"], index: 0, updated_at: T2 });
    m.session.set(USER);
    await flush();
    expect(getQueue).toHaveBeenCalledTimes(1);
    expect(get(m.sync.resumeOffer)?.slugs).toEqual(["a"]);
  });

  it("clears everything on logout", async () => {
    getQueue.mockResolvedValue({ slugs: ["a"], index: 0, updated_at: T2 });
    const m = await boot();
    expect(get(m.sync.resumeOffer)).not.toBeNull();
    change(m.audio, { slugs: ["a", "b"], index: 1 }); // stored copy + pending PUT
    getQueue.mockResolvedValue({ slugs: ["q"], index: 0, updated_at: "2027-01-01T00:00:00+00:00" });
    doc.dispatchEvent(new Event("visibilitychange"));
    await flush(); // offer is back
    expect(get(m.sync.resumeOffer)).not.toBeNull();
    m.audio.player.set({ playing: false, position: 12, set: { slug: "a" } } as never);
    m.session.set(null);
    expect(get(m.audio.player).set).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(get(m.sync.resumeOffer)).toBeNull();
    expect(get(m.audio.queue)).toEqual({ slugs: [], index: 0 });
    expect(reset).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(putQueue).not.toHaveBeenCalled(); // pending timer was cancelled
    doc.dispatchEvent(new Event("visibilitychange"));
    await flush();
    expect(getQueue).toHaveBeenCalledTimes(2); // none after logout
  });
});

describe("queue sync: stale stored queue", () => {
  it("playback with an empty queue clears a stored queue (one PUT [])", async () => {
    getQueue.mockResolvedValue({ slugs: ["a", "b"], index: 1, updated_at: T2 });
    const m = await boot(); // server queue becomes the local copy (offer shown)
    m.audio.queue.set({ slugs: [], index: 0 }); // e.g. dismissed, then a set is played singly
    m.audio.player.update((s) => ({ ...s, playing: true }));
    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ slugs: [], index: 0 });
    expect(get(m.sync.resumeOffer)).toBeNull();
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenCalledTimes(1);
    expect(putQueue).toHaveBeenCalledWith({ slugs: [], index: 0, base_updated_at: T2 }, undefined);
    // Further player updates while playing do not clear/PUT again.
    m.audio.player.update((s) => ({ ...s, position: 5 }));
    await vi.advanceTimersByTimeAsync(600);
    expect(putQueue).toHaveBeenCalledTimes(1);
  });

  it("accepting an offer does not clear it", async () => {
    getQueue.mockResolvedValue({ slugs: ["a", "b"], index: 1, updated_at: T2 });
    const m = await boot();
    await m.sync.acceptOffer(); // mock playQueue fills the queue, then playback starts
    m.audio.player.update((s) => ({ ...s, playing: true }));
    await vi.advanceTimersByTimeAsync(600);
    expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ slugs: ["a", "b"], index: 1 });
    expect(putQueue).not.toHaveBeenCalledWith({ slugs: [], index: 0, base_updated_at: expect.anything() }, undefined);
  });
});
