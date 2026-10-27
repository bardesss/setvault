// Keeps the play queue in sync: localStorage + server (last write wins), and
// offers (never autoplays) a queue found on the server or kept locally.
// Sync only runs while a user is signed in, and is wiped on logout.
import { writable, get } from "svelte/store";
import { getQueue, putQueue } from "#lib/api/queue.ts";
import { getSet } from "#lib/api/sets.ts";
import { onQueueChange, playQueue, player, queue, type PlayQueue } from "./audio";
import { session } from "./session";

export interface ResumeOffer { slugs: string[]; index: number; title: string }
export const resumeOffer = writable<ResumeOffer | null>(null);

const KEY = "setvault.playQueue";
const DEBOUNCE_MS = 500;

interface LocalQueue { slugs: string[]; index: number; updatedAt: string | null }

let started = false;
let userId: string | null = null;
/** The sync base: never loaded into `queue` except through an accepted offer. */
let local: LocalQueue | null = null;
let putTimer: ReturnType<typeof setTimeout> | null = null;
let fetchSeq = 0;
let epoch = 0;

function readLocal(): LocalQueue | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw);
    if (!v || !Array.isArray(v.slugs) || !v.slugs.every((s: unknown) => typeof s === "string")) return null;
    return {
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
  queue.set({ slugs: [], index: 0 });
}

async function sendQueue(): Promise<void> {
  putTimer = null;
  const q = get(queue);
  const myEpoch = epoch;
  try {
    // base_updated_at is echoed exactly as the server sent it (a string).
    const res = await putQueue({ slugs: q.slugs, index: q.index, base_updated_at: local?.updatedAt ?? null });
    if (myEpoch !== epoch) return;
    local = { slugs: local?.slugs ?? q.slugs, index: local?.index ?? q.index, updatedAt: res.updated_at };
    writeLocal();
    if (res.overwrote_newer) void fetchServerQueue(false);
  } catch { /* best-effort; the next change retries */ }
}

function onChange(q: PlayQueue): void {
  fetchSeq++; // an in-flight fetch must not clobber this fresh change
  local = { slugs: q.slugs.slice(), index: q.index, updatedAt: local?.updatedAt ?? null };
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
  void putQueue({ slugs: q.slugs, index: q.index, base_updated_at: local?.updatedAt ?? null }, { keepalive: true })
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
        local = { slugs: [], index: 0, updatedAt: server.updated_at };
        writeLocal();
        resumeOffer.set(null);
        return;
      }
      cand = { slugs: server.slugs, index: server.index, updatedAt: server.updated_at };
    } else if (startup && local && local.slugs.length > 0) {
      cand = local;
    }
    if (!cand) return;
    const index = clampIndex(cand.index, cand.slugs.length);
    cand = { slugs: cand.slugs, index, updatedAt: cand.updatedAt };
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
  player.subscribe((p) => { if (p.playing) resumeOffer.set(null); });
  session.subscribe((user) => {
    const id = user?.id ?? null;
    if (id === userId) return;
    if (userId !== null) clearAll(); // logout or a different user
    userId = id;
    if (id === null) return;
    local = readLocal();
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
