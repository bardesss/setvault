// Keeps the play queue in sync: localStorage + server (last write wins), and
// offers (never autoplays) a queue found on the server or kept locally.
// Sync only runs while a user is signed in, and is wiped on logout.
import { writable, get } from "svelte/store";
import { getQueue, putQueue } from "#lib/api/queue.ts";
import { getSet } from "#lib/api/sets.ts";
import { onQueueChange, playQueue, player, queue, reset, resetQueue, type PlayQueue } from "./audio";
import { session } from "./session";

export interface ResumeOffer { slugs: string[]; index: number; title: string }
export const resumeOffer = writable<ResumeOffer | null>(null);

const KEY = "setvault.playQueue";
const DEBOUNCE_MS = 500;

interface LocalQueue { userId: string; slugs: string[]; index: number; updatedAt: string | null }

let started = false;
let userId: string | null = null;
/** The sync base: never loaded into `queue` except through an accepted offer. */
let local: LocalQueue | null = null;
let putTimer: ReturnType<typeof setTimeout> | null = null;
let fetchSeq = 0;
let epoch = 0;

/** A copy stored by another user, or without an owner, is discarded. */
function readLocal(uid: string): LocalQueue | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw);
    if (!v || v.userId !== uid) {
      localStorage.removeItem(KEY);
      return null;
    }
    if (!Array.isArray(v.slugs) || !v.slugs.every((s: unknown) => typeof s === "string")) return null;
    return {
      userId: uid,
      slugs: v.slugs,
      index: Number.isInteger(v.index) ? v.index : 0,
      updatedAt: typeof v.updatedAt === "string" ? v.updatedAt : null,
    };
  } catch {
    return null;
  }
}

function writeLocal(): void {
  if (!local) return;
  try { localStorage.setItem(KEY, JSON.stringify(local)); } catch { /* unavailable */ }
}

function isNewer(serverAt: string | null): boolean {
  if (!serverAt) return false;
  if (!local?.updatedAt) return true;
  return Date.parse(serverAt) > Date.parse(local.updatedAt);
}

function clampIndex(index: number, length: number): number {
  return Math.max(0, Math.min(length - 1, Math.trunc(index) || 0));
}

function clearAll(): void {
  epoch++;
  fetchSeq++;
  if (putTimer) clearTimeout(putTimer);
  putTimer = null;
  local = null;
  try { localStorage.removeItem(KEY); } catch { /* unavailable */ }
  resumeOffer.set(null);
  resetQueue(); // also stops an in-flight advance
  reset(); // stop playback and drop the loaded set
}

async function sendQueue(): Promise<void> {
  putTimer = null;
  const q = get(queue);
  const myEpoch = epoch;
  try {
    // base_updated_at is echoed exactly as the server sent it (a string).
    const res = await putQueue({ slugs: q.slugs, index: q.index, base_updated_at: local?.updatedAt ?? null });
    if (myEpoch !== epoch) return;
    if (!userId) return;
    // A change made while the PUT was in flight keeps its own (newer) content.
    const keep = putTimer !== null && local;
    local = { userId, slugs: keep ? local!.slugs : q.slugs, index: keep ? local!.index : q.index, updatedAt: res.updated_at };
    writeLocal();
    if (res.overwrote_newer) void fetchServerQueue(false);
  } catch { /* best-effort; the next change retries */ }
}

function onChange(q: PlayQueue): void {
  if (userId === null) return;
  fetchSeq++; // an in-flight fetch must not clobber this fresh change
  local = { userId, slugs: q.slugs.slice(), index: q.index, updatedAt: local?.updatedAt ?? null };
  writeLocal();
  resumeOffer.set(null);
  if (putTimer) clearTimeout(putTimer);
  putTimer = setTimeout(() => void sendQueue(), DEBOUNCE_MS);
}

function flushOnPageHide(): void {
  if (!putTimer) return;
  clearTimeout(putTimer);
  putTimer = null;
  const q = get(queue);
  const myEpoch = epoch;
  void putQueue({ slugs: q.slugs, index: q.index, base_updated_at: local?.updatedAt ?? null }, { keepalive: true })
    .then((res) => {
      if (myEpoch !== epoch || !local) return;
      local = { ...local, updatedAt: res.updated_at };
      writeLocal();
    })
    .catch(() => undefined);
}

async function fetchServerQueue(startup: boolean): Promise<void> {
  if (!get(session)) return;
  const seq = ++fetchSeq;
  try {
    const server = await getQueue();
    if (seq !== fetchSeq) return;
    const serverNewer = isNewer(server.updated_at);
    let cand: LocalQueue | null = null;
    if (serverNewer) {
      if (server.slugs.length === 0) {
        // Cleared on another device: mirror it and drop any offer.
        local = { userId: userId!, slugs: [], index: 0, updatedAt: server.updated_at };
        writeLocal();
        resumeOffer.set(null);
        return;
      }
      cand = { userId: userId!, slugs: server.slugs, index: server.index, updatedAt: server.updated_at };
    } else if (startup && local && local.slugs.length > 0) {
      cand = local;
    }
    if (!cand) return;
    const index = clampIndex(cand.index, cand.slugs.length);
    cand = { userId: cand.userId, slugs: cand.slugs, index, updatedAt: cand.updatedAt };
    if (get(player).playing) {
      if (serverNewer) { local = cand; writeLocal(); }
      return;
    }
    const set = await getSet(cand.slugs[index]);
    if (seq !== fetchSeq || get(player).playing) return;
    if (serverNewer) { local = cand; writeLocal(); }
    resumeOffer.set({ slugs: cand.slugs, index, title: set.title });
  } catch { /* offline, signed out, or the set is gone: no offer */ }
}

export function startQueueSync(): void {
  if (started || typeof window === "undefined") return;
  started = true;
  onQueueChange(onChange);
  window.addEventListener("pagehide", flushOnPageHide);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void fetchServerQueue(false);
  });
  let wasPlaying = get(player).playing;
  player.subscribe((p) => {
    const started = p.playing && !wasPlaying;
    wasPlaying = p.playing;
    if (!p.playing) return;
    resumeOffer.set(null);
    if (!started) return;
    // Playing with nothing queued (a single set) while a queue is stored: the
    // stored copy is stale, so clear it (local + server). acceptOffer fills the
    // queue before playback starts, so it never lands here.
    if (userId !== null && get(queue).slugs.length === 0 && local && local.slugs.length > 0) {
      onChange({ slugs: [], index: 0 });
    }
  });
  session.subscribe((user) => {
    const id = user?.id ?? null;
    if (id === userId) return;
    if (userId !== null) clearAll(); // logout or a different user
    userId = id;
    if (id === null) return;
    local = readLocal(id);
    void fetchServerQueue(true);
  });
}

export async function acceptOffer(): Promise<void> {
  const offer = get(resumeOffer);
  if (!offer) return;
  resumeOffer.set(null);
  await playQueue(offer.slugs, offer.index);
}

export function dismissOffer(): void {
  resumeOffer.set(null);
}
