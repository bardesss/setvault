// Engine tests for the resume / continue-listening guard (#15). The engine is a
// module singleton, so each test re-imports it after resetting the module
// registry, with the API client, `$app/env` and the media element faked.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { get } from "svelte/store";

const putSetState = vi.fn(async (_slug: string, _state: unknown, _init?: RequestInit) => undefined);
const getSetState = vi.fn();

vi.mock("$app/env", () => ({ browser: true }));
vi.mock("#lib/api/sets.ts", () => ({
  getSetState: (slug: string) => getSetState(slug),
  putSetState: (slug: string, state: unknown, init?: RequestInit) =>
    putSetState(slug, state, init),
}));
vi.mock("#lib/api/tracklist.ts", () => ({ listTracklist: async () => [] }));

let lastAudio: FakeAudio | null = null;

class FakeAudio extends EventTarget {
  src = "";
  preload = "";
  currentTime = 0;
  duration = NaN;
  paused = true;
  playbackRate = 1;
  style: Record<string, string> = {};
  async play(): Promise<void> {
    this.paused = false;
    this.dispatchEvent(new Event("play"));
  }
  pause(): void {
    if (this.paused) return;
    this.paused = true;
    this.dispatchEvent(new Event("pause"));
  }
  remove(): void { /* detached */ }
  constructor() {
    super();
    lastAudio = this;
  }
}

let win: EventTarget;

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

function makeSet(slug = "a-set", duration: number | null = 3600) {
  return {
    slug, title: slug, duration_seconds: duration, artists: [],
    audio_stream_url: `/api/sets/${slug}/stream`,
  } as never;
}

async function engine() {
  return await import("./audio");
}

beforeEach(() => {
  vi.resetModules();
  lastAudio = null;
  vi.useFakeTimers();
  putSetState.mockClear();
  getSetState.mockReset();
  win = new EventTarget();
  vi.stubGlobal("Audio", FakeAudio);
  vi.stubGlobal("window", win);
  vi.stubGlobal("document", { body: { appendChild: () => undefined } });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("audio engine save guard", () => {
  it("does not save while idle", async () => {
    getSetState.mockResolvedValue({ position_seconds: 0, completed: false, playback_rate: 1 });
    const audio = await engine();
    await audio.load(makeSet());
    await vi.advanceTimersByTimeAsync(10_000);
    win.dispatchEvent(new Event("pagehide"));
    await vi.advanceTimersByTimeAsync(0);
    expect(putSetState).not.toHaveBeenCalled();
  });

  it("restoring does not write position 0", async () => {
    const remote = deferred<{ position_seconds: number; completed: boolean; playback_rate: number }>();
    getSetState.mockReturnValue(remote.promise);
    const audio = await engine();
    const loading = audio.load(makeSet());
    // The interval must not fire with the placeholder position during the fetch.
    await vi.advanceTimersByTimeAsync(10_000);
    remote.resolve({ position_seconds: 120, completed: false, playback_rate: 1 });
    await loading;
    expect(get(audio.player).position).toBe(120);
    expect(lastAudio?.currentTime).toBe(120);
    expect(putSetState).not.toHaveBeenCalled();

    await audio.play();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(putSetState).toHaveBeenCalled();
    for (const [, state] of putSetState.mock.calls) {
      expect((state as { position_seconds: number }).position_seconds).toBeGreaterThanOrEqual(120);
    }
  });

  it("setRate during restore does not save", async () => {
    const remote = deferred<{ position_seconds: number; completed: boolean; playback_rate: number }>();
    getSetState.mockReturnValue(remote.promise);
    const audio = await engine();
    const loading = audio.load(makeSet());
    audio.setRate(1.5);
    remote.resolve({ position_seconds: 120, completed: false, playback_rate: 1.25 });
    await loading;
    await vi.advanceTimersByTimeAsync(0);
    expect(get(audio.player).playbackRate).toBe(1.25);
    expect(putSetState).not.toHaveBeenCalled();
  });

  it("reopening a completed set does not reset completed unless it plays", async () => {
    getSetState.mockResolvedValue({ position_seconds: 3600, completed: true, playback_rate: 1 });
    const audio = await engine();
    await audio.load(makeSet("done-set"));
    audio.setRate(1.1);
    await audio.load(makeSet("other-set")); // switching away flushes only if played
    await vi.advanceTimersByTimeAsync(10_000);
    expect(putSetState).not.toHaveBeenCalled();
  });

  it("saves only while playing and flushes on pause and pagehide", async () => {
    getSetState.mockResolvedValue({ position_seconds: 30, completed: false, playback_rate: 1 });
    const audio = await engine();
    await audio.load(makeSet());
    await audio.play();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(putSetState).toHaveBeenCalledTimes(1);
    audio.pause();
    await vi.advanceTimersByTimeAsync(0);
    expect(putSetState).toHaveBeenCalledTimes(2); // flush on pause
    await vi.advanceTimersByTimeAsync(20_000);
    expect(putSetState).toHaveBeenCalledTimes(2); // interval stopped
    win.dispatchEvent(new Event("pagehide"));
    await vi.advanceTimersByTimeAsync(0);
    expect(putSetState).toHaveBeenCalledTimes(3);
    expect(putSetState.mock.calls[2][2]).toEqual({ keepalive: true });
    expect(putSetState.mock.calls[0][2]).toBeUndefined();
  });
});
