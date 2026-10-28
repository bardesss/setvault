// Queue tests: advancing on `ended`, next/prev falling through to neighbouring
// sets, and a set page not taking over playback. Same harness as audio-engine.test.ts.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { get } from "svelte/store";
import { ApiError } from "#lib/api/client.ts";

const putSetState = vi.fn(async (_slug: string, _state: unknown, _init?: RequestInit) => undefined);
const getSetState = vi.fn();
const getSet = vi.fn();

vi.mock("$app/env", () => ({ browser: true }));
vi.mock("#lib/api/sets.ts", () => ({
  getSet: (slug: string) => getSet(slug),
  getSetState: (slug: string) => getSetState(slug),
  putSetState: (slug: string, state: unknown, init?: RequestInit) =>
    putSetState(slug, state, init),
}));
vi.mock("#lib/api/tracklist.ts", () => ({
  listTracklist: async (slug: string) => tracklists[slug] ?? [],
}));

let tracklists: Record<string, { start_seconds: number }[]> = {};
let constructed = 0;
let lastAudio: FakeAudio | null = null;
let playImpl: (a: FakeAudio) => Promise<void>;

class FakeAudio extends EventTarget {
  srcs: string[] = [];
  get src(): string { return this.srcs.at(-1) ?? ""; }
  set src(v: string) { this.srcs.push(v); }
  preload = "";
  currentTime = 0;
  duration = NaN;
  paused = true;
  playbackRate = 1;
  style: Record<string, string> = {};
  loads = 0;
  removeAttribute(name: string): void { if (name === "src") this.srcs.push(""); }
  load(): void { this.loads++; }
  play(): Promise<void> { return playImpl(this); }
  pause(): void {
    if (this.paused) return;
    this.paused = true;
    this.dispatchEvent(new Event("pause"));
  }
  constructor() {
    super();
    constructed++;
    lastAudio = this;
  }
}

function makeSet(slug: string) {
  return {
    slug, title: slug, duration_seconds: 3600, artists: [],
    audio_stream_url: `/api/sets/${slug}/stream`,
  } as never;
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

async function engine() {
  return await import("./audio");
}

async function endCurrent() {
  lastAudio!.dispatchEvent(new Event("ended"));
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  lastAudio = null;
  constructed = 0;
  tracklists = {};
  putSetState.mockReset().mockResolvedValue(undefined);
  getSetState.mockReset();
  getSetState.mockResolvedValue({ position_seconds: 0, completed: false, playback_rate: 1 });
  getSet.mockReset();
  getSet.mockImplementation(async (slug: string) => makeSet(slug));
  playImpl = async (a) => { a.paused = false; a.dispatchEvent(new Event("play")); };
  vi.stubGlobal("Audio", FakeAudio);
  vi.stubGlobal("window", new EventTarget());
  vi.stubGlobal("document", { body: { appendChild: () => undefined } });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const slugs = ["s1", "s2", "s3"];

describe("play queue", () => {
  it("playQueue loads the start set and plays", async () => {
    const audio = await engine();
    const play = vi.spyOn(FakeAudio.prototype, "play");
    await audio.playQueue(slugs, 1);
    expect(getSet).toHaveBeenCalledWith("s2");
    expect(getSet).not.toHaveBeenCalledWith("s1");
    expect(play).toHaveBeenCalled();
    expect(get(audio.player).set?.slug).toBe("s2");
    expect(get(audio.queue)).toEqual({ slugs, index: 1 });
    play.mockRestore();
  });

  it("ended advances to the next set and plays", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    await endCurrent();
    expect(get(audio.player).set?.slug).toBe("s2");
    expect(get(audio.queue).index).toBe(1);
    expect(get(audio.player).playing).toBe(true);
  });

  it("ended on the last set stops and keeps the queue", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 2);
    await endCurrent();
    expect(get(audio.player).set?.slug).toBe("s3");
    expect(get(audio.player).playing).toBe(false);
    expect(get(audio.queue)).toEqual({ slugs, index: 2 });
  });

  it("advance skips a set that 404s", async () => {
    getSet.mockImplementation(async (slug: string) => {
      if (slug === "s2") throw new ApiError(404, "not found");
      return makeSet(slug);
    });
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    await endCurrent();
    expect(get(audio.player).set?.slug).toBe("s3");
    expect(get(audio.queue).index).toBe(2);
  });

  it("advancing into a completed set starts from 0", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    getSetState.mockResolvedValue({ position_seconds: 500, completed: true, playback_rate: 1 });
    await endCurrent();
    expect(get(audio.player).set?.slug).toBe("s2");
    expect(lastAudio?.currentTime).toBe(0);
    expect(get(audio.player).position).toBe(0);
  });

  it("next at the last track falls through to the next set", async () => {
    tracklists = { s1: [{ start_seconds: 0 }, { start_seconds: 600 }] };
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    audio.seekTo(700);
    lastAudio!.dispatchEvent(new Event("timeupdate"));
    audio.next();
    await vi.advanceTimersByTimeAsync(0);
    expect(get(audio.player).set?.slug).toBe("s2");
  });

  it("next with a later track seeks instead of leaving the set", async () => {
    tracklists = { s1: [{ start_seconds: 0 }, { start_seconds: 600 }] };
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    audio.next();
    await vi.advanceTimersByTimeAsync(0);
    expect(get(audio.player).set?.slug).toBe("s1");
    expect(lastAudio?.currentTime).toBe(600);
  });

  it("prev near the start goes to the previous set", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 1);
    getSetState.mockResolvedValue({ position_seconds: 900, completed: false, playback_rate: 1 });
    audio.prev();
    await vi.advanceTimersByTimeAsync(0);
    expect(get(audio.player).set?.slug).toBe("s1");
    expect(get(audio.queue).index).toBe(0);
    expect(lastAudio?.currentTime).toBe(0);
  });

  it("prev mid-set rewinds within the set", async () => {
    tracklists = { s2: [{ start_seconds: 0 }, { start_seconds: 600 }] };
    const audio = await engine();
    await audio.playQueue(slugs, 1);
    audio.seekTo(700);
    lastAudio!.dispatchEvent(new Event("timeupdate"));
    audio.prev();
    await vi.advanceTimersByTimeAsync(0);
    expect(get(audio.player).set?.slug).toBe("s2");
    expect(lastAudio?.currentTime).toBe(600);
  });

  it("advance keeps the same audio element", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    const el = lastAudio;
    await endCurrent();
    await endCurrent();
    expect(get(audio.queue).index).toBe(2);
    expect(constructed).toBe(1);
    expect(lastAudio).toBe(el);
  });

  it("rejected play keeps queue", async () => {
    playImpl = async () => { throw new DOMException("blocked", "NotAllowedError"); };
    const audio = await engine();
    await expect(audio.playQueue(slugs, 1)).resolves.toBeUndefined();
    expect(get(audio.queue)).toEqual({ slugs, index: 1 });
    expect(get(audio.player).playing).toBe(false);
    expect(get(audio.player).set?.slug).toBe("s2");
  });

  it("playSingle clears the queue", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    await audio.playSingle(makeSet("solo"));
    expect(get(audio.queue)).toEqual({ slugs: [], index: 0 });
    expect(get(audio.player).set?.slug).toBe("solo");
    expect(get(audio.player).playing).toBe(true);
    await endCurrent();
    expect(get(audio.player).set?.slug).toBe("solo");
  });

  it("onQueueChange fires on playQueue, advance and playSingle", async () => {
    const audio = await engine();
    const seen: { slugs: string[]; index: number }[] = [];
    audio.onQueueChange((q) => seen.push(structuredClone(q)));
    await audio.playQueue(slugs, 0);
    expect(seen.at(-1)).toEqual({ slugs, index: 0 });
    await endCurrent();
    expect(seen.at(-1)).toEqual({ slugs, index: 1 });
    await audio.playSingle(makeSet("solo"));
    expect(seen.at(-1)).toEqual({ slugs: [], index: 0 });
    expect(seen).toHaveLength(3);
  });

  it("playSingle with an empty queue still notifies exactly once", async () => {
    const audio = await engine();
    const seen: { slugs: string[]; index: number }[] = [];
    audio.onQueueChange((q) => seen.push(structuredClone(q)));
    await audio.playSingle(makeSet("solo"));
    expect(seen).toEqual([{ slugs: [], index: 0 }]);
  });

  it("shouldAutoload is false while a queue is loaded, playing or paused", async () => {
    const audio = await engine();
    expect(audio.shouldAutoload()).toBe(true);
    await audio.playQueue(slugs, 1);
    expect(audio.shouldAutoload()).toBe(false);
    audio.pause();
    expect(audio.shouldAutoload()).toBe(false); // a paused queue is still a queue
  });

  it("shouldAutoload is false while a single set is playing", async () => {
    const audio = await engine();
    await audio.playSingle(makeSet("solo"));
    expect(get(audio.queue).slugs).toEqual([]);
    expect(audio.shouldAutoload()).toBe(false);
    audio.pause();
    expect(audio.shouldAutoload()).toBe(true);
  });

  it("playQueue with no slugs is a no-op and a far startIndex is clamped", async () => {
    const audio = await engine();
    await audio.playQueue([], 0);
    expect(getSet).not.toHaveBeenCalled();
    expect(get(audio.queue)).toEqual({ slugs: [], index: 0 });
    await audio.playQueue(slugs, 9);
    expect(getSet).toHaveBeenCalledWith("s3");
    expect(get(audio.queue)).toEqual({ slugs, index: 2 });
  });
});

describe("seekInSet", () => {
  it("seeks within the current set", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    getSet.mockClear();
    await audio.seekInSet("s1", 120);
    expect(lastAudio?.currentTime).toBe(120);
    expect(getSet).not.toHaveBeenCalled();
    expect(get(audio.queue)).toEqual({ slugs, index: 0 });
  });

  it("on another set plays it singly, clears the queue and seeks", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    await audio.seekInSet("page-set", 90);
    expect(getSet).toHaveBeenCalledWith("page-set");
    expect(get(audio.player).set?.slug).toBe("page-set");
    expect(get(audio.player).playing).toBe(true);
    expect(get(audio.queue)).toEqual({ slugs: [], index: 0 });
    expect(lastAudio?.currentTime).toBe(90);
  });

  it("on another set seeks before play() is called", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    const order: string[] = [];
    playImpl = async (a) => {
      order.push(`play@${a.currentTime}`);
      a.paused = false;
      a.dispatchEvent(new Event("play"));
    };
    await audio.seekInSet("page-set", 90);
    expect(order).toEqual(["play@90"]);
  });
});

describe("load and reset", () => {
  it("load switches the source without waiting for the outgoing state save", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    const pending = deferred<undefined>();
    putSetState.mockImplementation(() => pending.promise);
    lastAudio!.currentTime = 30;
    await audio.load(makeSet("other"));
    expect(lastAudio!.src).toContain("other");
    expect(putSetState).toHaveBeenCalledWith("s1", expect.objectContaining({ position_seconds: expect.any(Number) }), undefined);
    pending.resolve(undefined);
  });

  it("reset stops playback, clears the source, the player and the queue", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 1);
    const loadsBefore = lastAudio!.loads;
    audio.reset();
    expect(get(audio.player).set).toBeNull();
    expect(get(audio.player).playing).toBe(false);
    expect(lastAudio!.paused).toBe(true);
    expect(lastAudio!.src).toBe("");
    expect(lastAudio!.loads).toBe(loadsBefore + 1);
    expect(get(audio.queue)).toEqual({ slugs, index: 1 }); // queue is reset separately via resetQueue
  });

  it("reset abandons an in-flight load", async () => {
    const audio = await engine();
    const late = deferred<never>();
    getSet.mockImplementation(async () => late.promise);
    void audio.playQueue(slugs, 0);
    await vi.advanceTimersByTimeAsync(0);
    audio.reset();
    late.resolve(makeSet("s1"));
    await vi.advanceTimersByTimeAsync(0);
    expect(get(audio.player).set).toBeNull();
  });
});

describe("queue races and edge cases", () => {
  it("a late getSet after playSingle never loads", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    const late = deferred<never>();
    getSet.mockImplementation(async (slug: string) => (slug === "s2" ? late.promise : makeSet(slug)));
    audio.next();
    await audio.playSingle(makeSet("other"));
    late.resolve(makeSet("s2"));
    await vi.advanceTimersByTimeAsync(0);
    expect(get(audio.player).set?.slug).toBe("other");
    expect(get(audio.queue)).toEqual({ slugs: [], index: 0 });
    expect(lastAudio?.srcs.some((s) => s.includes("s2"))).toBe(false);
  });

  it("resetQueue empties the queue silently and abandons an in-flight advance", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    const seen: unknown[] = [];
    audio.onQueueChange((q) => seen.push(q));
    const late = deferred<never>();
    getSet.mockImplementation(async (slug: string) => (slug === "s2" ? late.promise : makeSet(slug)));
    audio.next();
    audio.resetQueue();
    late.resolve(makeSet("s2"));
    await vi.advanceTimersByTimeAsync(0);
    expect(get(audio.queue)).toEqual({ slugs: [], index: 0 });
    expect(get(audio.player).set?.slug).toBe("s1");
    expect(lastAudio?.srcs.some((s) => s.includes("s2"))).toBe(false);
    expect(seen).toEqual([]);
    // A stale pendingIndex must not leak into the next press.
    expect(audio.shouldAutoload()).toBe(false); // s1 is still playing
  });

  it("two quick next() presses move two sets ahead", async () => {
    const audio = await engine();
    await audio.playQueue(["s1", "s2", "s3", "s4"], 0);
    audio.next();
    audio.next();
    await vi.advanceTimersByTimeAsync(0);
    expect(get(audio.player).set?.slug).toBe("s3");
    expect(get(audio.queue).index).toBe(2);
    expect(lastAudio?.srcs.some((s) => s.includes("s2"))).toBe(false);
  });

  it("commits the queue index once the audio source switched, without waiting for the state flush", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    const flush = deferred<undefined>();
    putSetState.mockImplementationOnce(async () => flush.promise);
    audio.next();
    await vi.advanceTimersByTimeAsync(0);
    expect(lastAudio?.src).toContain("s2"); // the flush PUT is still pending
    expect(get(audio.queue).index).toBe(1);
    flush.resolve(undefined);
    await vi.advanceTimersByTimeAsync(0);
    expect(lastAudio?.src).toContain("s2");
  });

  it("re-targeting the loaded set restarts it when it is completed", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    audio.seekTo(3500);
    getSetState.mockResolvedValue({ position_seconds: 3500, completed: true, playback_rate: 1 });
    await audio.playQueue(slugs, 0);
    expect(lastAudio?.currentTime).toBe(0);
    expect(get(audio.player).position).toBe(0);
  });

  it("re-targeting the loaded set keeps its position when not completed", async () => {
    const audio = await engine();
    await audio.playQueue(slugs, 0);
    audio.seekTo(300);
    await audio.playQueue(slugs, 0);
    expect(lastAudio?.currentTime).toBe(300);
  });

  it("prev skips a 404 set by scanning backwards", async () => {
    getSet.mockImplementation(async (slug: string) => {
      if (slug === "s2") throw new ApiError(404, "not found");
      return makeSet(slug);
    });
    const audio = await engine();
    await audio.playQueue(slugs, 2);
    audio.prev();
    await vi.advanceTimersByTimeAsync(0);
    expect(get(audio.player).set?.slug).toBe("s1");
    expect(get(audio.queue).index).toBe(0);
  });

  it("notifies only on change, before play settles, and not when superseded", async () => {
    const audio = await engine();
    const seen: unknown[] = [];
    audio.onQueueChange((q) => seen.push(structuredClone(q)));
    const held = deferred<void>();
    playImpl = async (a) => { await held.promise; a.paused = false; a.dispatchEvent(new Event("play")); };
    const starting = audio.playQueue(slugs, 2);
    await vi.advanceTimersByTimeAsync(0);
    expect(seen).toHaveLength(1); // before play() settled
    held.resolve();
    await starting;
    audio.next(); // already last: nothing changes
    await vi.advanceTimersByTimeAsync(0);
    expect(seen).toHaveLength(1);
  });
});
