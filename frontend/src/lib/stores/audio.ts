import { writable, get } from "svelte/store";
import { browser } from "$app/env";
import { _ } from "svelte-i18n";
import type { SetDetail } from "#lib/api/sets.ts";
import { getSet, getSetState, putSetState } from "#lib/api/sets.ts";
import { listTracklist, type TracklistEntry } from "#lib/api/tracklist.ts";

export interface PlayerState {
  set: SetDetail | null;
  playing: boolean;
  position: number;
  duration: number;
  playbackRate: number;
  loopStart: number | null;
  loopEnd: number | null;
  buffering: boolean;
}

const initial: PlayerState = {
  set: null, playing: false, position: 0, duration: 0,
  playbackRate: 1, loopStart: null, loopEnd: null, buffering: false,
};

export const player = writable<PlayerState>(initial);
export const fullscreenOpen = writable<boolean>(false);

export interface PlayQueue { slugs: string[]; index: number }
export const queue = writable<PlayQueue>({ slugs: [], index: 0 });

// ---- pure helpers (unit-tested) -------------------------------------------
export function clampRate(r: number): number {
  if (!Number.isFinite(r)) return 1;
  return Math.max(0.5, Math.min(2, Math.round(r * 100) / 100));
}

// Kept here for existing importers.
export { fmtDuration as formatTime } from "#lib/format.ts";

export function pickNext<T extends { start_seconds: number }>(entries: T[], position: number): number | null {
  for (const e of entries) if (e.start_seconds > position + 0.5) return e.start_seconds;
  return null;
}

export function pickPrev<T extends { start_seconds: number }>(entries: T[], position: number): number {
  const REWIND = 2;
  for (let i = entries.length - 1; i >= 0; i--) {
    if (entries[i].start_seconds < position - REWIND) return entries[i].start_seconds;
  }
  return 0;
}

// ---- engine singleton ------------------------------------------------------
let el: HTMLAudioElement | null = null;
let tracklist: TracklistEntry[] = [];
let saveTimer: ReturnType<typeof setInterval> | null = null;
let initialized = false;
// Save guard (#15): nothing is written while the resume position is being
// restored, nor for a set that hasn't actually played since it was loaded, so
// merely opening a set never creates or overwrites its saved state.
let restoring = false;
let played = false;
let loadToken = 0;
let queueToken = 0;
let queueListener: ((q: PlayQueue) => void) | null = null;

function patch(p: Partial<PlayerState>): void {
  player.update((s) => ({ ...s, ...p }));
}

async function saveState(init?: RequestInit): Promise<void> {
  const st = get(player);
  if (!el || !st.set || restoring || !played) return;
  const total = st.set.duration_seconds ?? st.duration ?? 0;
  const completed = total > 0 ? st.position >= total * 0.97 : false;
  try {
    await putSetState(st.set.slug, {
      position_seconds: st.position,
      completed,
      playback_rate: st.playbackRate,
    }, init);
  } catch { /* best-effort */ }
}

function startSaving(): void {
  if (saveTimer) return;
  saveTimer = setInterval(() => void saveState(), 5000);
}

function stopSaving(): void {
  if (saveTimer) clearInterval(saveTimer);
  saveTimer = null;
}

function onPageHide(): void { void saveState({ keepalive: true }); }

export function init(): void {
  if (!browser || initialized) return;
  initialized = true;
  el = new Audio();
  el.preload = "metadata";
  // The element must be connected to the document or browsers (notably
  // headless Chromium under the autoplay policy) refuse to start playback on
  // a detached, unmuted media element. Hidden — it only produces sound.
  el.style.display = "none";
  document.body.appendChild(el);
  el.addEventListener("timeupdate", () => {
    if (!el) return;
    const st = get(player);
    if (st.loopStart !== null && st.loopEnd !== null && el.currentTime >= st.loopEnd) {
      el.currentTime = st.loopStart;
      return;
    }
    patch({ position: el.currentTime });
  });
  el.addEventListener("durationchange", () => patch({ duration: el?.duration ?? 0 }));
  el.addEventListener("play", () => {
    patch({ playing: true });
    if (!restoring) played = true;
    startSaving();
  });
  el.addEventListener("pause", () => {
    patch({ playing: false });
    stopSaving();
    void saveState();
  });
  el.addEventListener("waiting", () => patch({ buffering: true }));
  el.addEventListener("playing", () => patch({ buffering: false }));
  el.addEventListener("ended", () => {
    patch({ playing: false });
    stopSaving();
    void saveState();
    const q = get(queue);
    if (pendingIndex === null && q.index < q.slugs.length - 1) void advanceTo(q.index + 1);
  });
  if (typeof window !== "undefined") window.addEventListener("pagehide", onPageHide);
}

function setMediaSession(set: SetDetail): void {
  if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
  try {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: set.title,
      artist: set.artists.map((a) => a.name).join(", ") || get(_)("player.unknown_artist"),
      artwork: [
        { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
        { src: "/icons/icon-256.png", sizes: "256x256", type: "image/png" },
        { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      ],
    });
    navigator.mediaSession.setActionHandler?.("play", () => void play());
    navigator.mediaSession.setActionHandler?.("pause", () => pause());
    navigator.mediaSession.setActionHandler?.("seekbackward", () => seekBy(-5));
    navigator.mediaSession.setActionHandler?.("seekforward", () => seekBy(5));
    navigator.mediaSession.setActionHandler?.("previoustrack", () => prev());
    navigator.mediaSession.setActionHandler?.("nexttrack", () => next());
  } catch { /* unsupported */ }
}

/** Idempotent: same set already loaded → no-op; different → switch + resume. */
export async function load(set: SetDetail, opts?: { restartCompleted?: boolean }): Promise<void> {
  if (!browser) return;
  if (!initialized) init();
  const cur = get(player);
  if (cur.set?.slug === set.slug) return;
  // Flush the outgoing set (only if it played). saveState snapshots the player
  // synchronously, so the source can switch at once without waiting for the PUT.
  if (cur.set) void saveState();
  if (!el) return;
  const token = ++loadToken;
  restoring = true;
  played = false;
  stopSaving();
  el.src = set.audio_stream_url;
  patch({ set, position: 0, duration: 0, loopStart: null, loopEnd: null });
  setMediaSession(set);
  tracklist = [];
  try {
    try {
      const entries = await listTracklist(set.slug);
      if (token === loadToken) tracklist = entries.slice().sort((a, b) => a.start_seconds - b.start_seconds);
    } catch { /* prev/next falls back */ }
    try {
      const remote = await getSetState(set.slug);
      if (token !== loadToken || !el) return;
      if (opts?.restartCompleted && remote.completed) {
        // A finished set reached through the queue plays from the top.
      } else if (remote.position_seconds > 0) {
        el.currentTime = remote.position_seconds;
        patch({ position: remote.position_seconds });
      }
      if (remote.playback_rate) setRate(remote.playback_rate);
    } catch { /* no prior state */ }
  } finally {
    if (token === loadToken) {
      restoring = false;
      // Playback started while restoring (autoplay, an early click): it counts.
      if (el && !el.paused) {
        played = true;
        startSaving();
      }
    }
  }
}

export async function play(): Promise<void> { try { await el?.play(); } catch { /* autoplay block */ } }
export function pause(): void { el?.pause(); }
export function toggle(): void { if (!el) return; el.paused ? void play() : pause(); }

export function seekTo(seconds: number): void {
  if (!el) return;
  el.currentTime = Math.max(0, Math.min(el.duration || Infinity, seconds));
}
export function seekBy(delta: number): void {
  if (!el) return;
  seekTo((el.currentTime || 0) + delta);
}

export function setRate(rate: number): void {
  const r = clampRate(rate);
  if (el) el.playbackRate = r;
  patch({ playbackRate: r });
  void saveState();
}

export function setLoopStart(): void {
  if (!el) return;
  const start = el.currentTime;
  player.update((s) => ({ ...s, loopStart: start, loopEnd: s.loopEnd !== null && s.loopEnd <= start ? null : s.loopEnd }));
}
export function setLoopEnd(): void {
  if (!el) return;
  const pos = el.currentTime;
  player.update((s) => {
    const start = s.loopStart === null || pos <= s.loopStart ? Math.max(0, pos - 0.01) : s.loopStart;
    return { ...s, loopStart: start, loopEnd: pos };
  });
}
export function clearLoop(): void { patch({ loopStart: null, loopEnd: null }); }

// ---- play queue -------------------------------------------------------------
export function onQueueChange(fn: (q: PlayQueue) => void): void { queueListener = fn; }

function notifyQueue(): void { queueListener?.(get(queue)); }

/** True when a set page may load its set into the idle player on mount. */
export function shouldAutoload(): boolean {
  return get(queue).slugs.length === 0 && !get(player).playing;
}

/** Queue index an in-flight advance is heading for, so quick presses stack. */
let pendingIndex: number | null = null;

/** Load and play the first existing queue entry from `from`, stepping by `step`
 *  (a 404 set is skipped). Reuses the one audio element; the queue index is
 *  committed once `load` has switched the source. A rejected play() leaves the
 *  queue in place and paused. Returns whether an entry was committed. */
async function advanceTo(from: number, step: 1 | -1 = 1, fromStart = false): Promise<boolean> {
  const token = ++queueToken;
  pendingIndex = from;
  const { slugs } = get(queue);
  try {
    for (let i = from; i >= 0 && i < slugs.length; i += step) {
      pendingIndex = i;
      let set: SetDetail;
      try {
        set = await getSet(slugs[i]);
      } catch (e) {
        if (token !== queueToken) return false;
        if ((e as { status?: number }).status === 404) continue; // recycled / unpublished
        return false;
      }
      if (token !== queueToken) return false;
      const alreadyLoaded = get(player).set?.slug === set.slug;
      await load(set, { restartCompleted: true });
      if (token !== queueToken) return false;
      let restart = fromStart;
      if (alreadyLoaded && !restart) {
        // load() was a no-op: a finished set still has to start from the top.
        try { restart = (await getSetState(set.slug)).completed; } catch { /* keep position */ }
        if (token !== queueToken) return false;
      }
      if (restart) { seekTo(0); patch({ position: 0 }); }
      const moved = get(queue).index !== i;
      queue.update((q) => ({ ...q, index: i }));
      if (moved) notifyQueue();
      await play();
      return true;
    }
    return false;
  } finally {
    if (token === queueToken) pendingIndex = null;
  }
}

export async function playQueue(slugs: string[], startIndex = 0): Promise<void> {
  if (!browser || slugs.length === 0) return;
  if (!initialized) init();
  const index = Math.max(0, Math.min(slugs.length - 1, Math.trunc(startIndex) || 0));
  queue.set({ slugs: slugs.slice(), index });
  notifyQueue();
  await advanceTo(index);
}

/** Drop the queue without notifying and abandon any in-flight advance (logout). */
export function resetQueue(): void {
  queueToken++;
  pendingIndex = null;
  queue.set({ slugs: [], index: 0 });
}

/** Stop and empty the player entirely (logout): no source, no set, no tracklist,
 *  and any in-flight load or advance is abandoned. The queue is reset separately. */
export function reset(): void {
  // No final save: the session is already gone by the time logout reaches here.
  el?.pause();
  if (el) {
    el.removeAttribute("src");
    el.load();
  }
  stopSaving();
  restoring = false;
  played = false;
  loadToken++;
  queueToken++;
  pendingIndex = null;
  tracklist = [];
  player.set({ ...initial });
  // Don't leave the previous user's set on the lock screen / notification.
  try { if ("mediaSession" in navigator) navigator.mediaSession.metadata = null; } catch { /* unsupported */ }
}

/** Play one set on its own: the queue is cleared. `startAt` (seconds) replaces
 *  the resume position and is applied after the load, before playback starts. */
export async function playSingle(set: SetDetail, startAt?: number): Promise<void> {
  queueToken++;
  pendingIndex = null;
  queue.set({ slugs: [], index: 0 });
  notifyQueue();
  await load(set);
  if (startAt !== undefined) seekTo(startAt);
  await play();
}

/** Seek within `slug`; if another set is current, start `slug` singly at `seconds`. */
export async function seekInSet(slug: string, seconds: number): Promise<void> {
  if (get(player).set?.slug === slug) { seekTo(seconds); return; }
  try {
    await playSingle(await getSet(slug), seconds);
  } catch { /* set unavailable */ }
}

export function next(): void {
  const t = pickNext(tracklist, get(player).position);
  if (t !== null) { seekTo(t); return; }
  const q = get(queue);
  const base = pendingIndex ?? q.index;
  if (base < q.slugs.length - 1) void advanceTo(base + 1);
}
export function prev(): void {
  const position = get(player).position;
  const t = pickPrev(tracklist, position);
  const q = get(queue);
  const base = pendingIndex ?? q.index;
  if (t === 0 && position <= 3 && base > 0) void advanceTo(base - 1, -1, true);
  else seekTo(t);
}
