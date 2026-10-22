import { writable, get } from "svelte/store";
import { browser } from "$app/env";
import type { SetDetail } from "#lib/api/sets.ts";
import { getSetState, putSetState } from "#lib/api/sets.ts";
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

// ---- pure helpers (unit-tested) -------------------------------------------
export function clampRate(r: number): number {
  if (!Number.isFinite(r)) return 1;
  return Math.max(0.5, Math.min(2, Math.round(r * 100) / 100));
}

export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
  return `${m}:${String(ss).padStart(2, "0")}`;
}

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

/** The persistent media element — Waveform binds to it via wavesurfer `media`. */
export function getElement(): HTMLAudioElement | null {
  return el;
}

function patch(p: Partial<PlayerState>): void {
  player.update((s) => ({ ...s, ...p }));
}

async function saveState(): Promise<void> {
  const st = get(player);
  if (!el || !st.set || restoring || !played) return;
  const total = st.set.duration_seconds ?? st.duration ?? 0;
  const completed = total > 0 ? st.position >= total * 0.97 : false;
  try {
    await putSetState(st.set.slug, {
      position_seconds: st.position,
      completed,
      playback_rate: st.playbackRate,
    });
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

function onPageHide(): void { void saveState(); }

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
  });
  if (typeof window !== "undefined") window.addEventListener("pagehide", onPageHide);
}

function setMediaSession(set: SetDetail): void {
  if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
  try {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: set.title,
      artist: set.artists.map((a) => a.name).join(", ") || "Unknown",
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
export async function load(set: SetDetail): Promise<void> {
  if (!browser) return;
  if (!initialized) init();
  const cur = get(player);
  if (cur.set?.slug === set.slug) return;
  if (cur.set) await saveState(); // flush outgoing (only if it played)
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
      if (remote.position_seconds > 0) {
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

export function next(): void {
  const t = pickNext(tracklist, get(player).position);
  if (t !== null) seekTo(t);
}
export function prev(): void { seekTo(pickPrev(tracklist, get(player).position)); }

export function dispose(): void {
  stopSaving();
  if (typeof window !== "undefined") window.removeEventListener("pagehide", onPageHide);
  restoring = false;
  played = false;
  loadToken++;
  el?.pause();
  el?.remove();
  el = null;
  initialized = false;
  player.set(initial);
}
