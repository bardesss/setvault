// Keeps the play queue in sync: localStorage + server (last write wins), and
// offers (never autoplays) a newer queue found on the server.
import { writable, get } from "svelte/store";
import { getQueue, putQueue } from "#lib/api/queue.ts";
import { getSet } from "#lib/api/sets.ts";
import { onQueueChange, playQueue, player, queue, type PlayQueue } from "./audio";

export interface ResumeOffer { slugs: string[]; index: number; title: string }
export const resumeOffer = writable<ResumeOffer | null>(null);

const KEY = "setvault.playQueue";
const DEBOUNCE_MS = 500;

interface LocalQueue { slugs: string[]; index: number; updatedAt: string | null }

let started = false;
let local: LocalQueue | null = null;
let putTimer: ReturnType<typeof setTimeout> | null = null;
let fetchSeq = 0;

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

async function sendQueue(): Promise<void> {
  putTimer = null;
  const q = local ?? get(queue);
  try {
    // base_updated_at is echoed exactly as the server sent it (a string).
    const res = await putQueue({ slugs: q.slugs, index: q.index, base_updated_at: local?.updatedAt ?? null });
    local = { slugs: q.slugs, index: q.index, updatedAt: res.updated_at };
    writeLocal();
    if (res.overwrote_newer) void fetchServerQueue();
  } catch { /* best-effort; the next change retries */ }
}

function onChange(q: PlayQueue): void {
  local = { slugs: q.slugs.slice(), index: q.index, updatedAt: local?.updatedAt ?? null };
  writeLocal();
  resumeOffer.set(null);
  if (putTimer) clearTimeout(putTimer);
  putTimer = setTimeout(() => void sendQueue(), DEBOUNCE_MS);
}

async function fetchServerQueue(): Promise<void> {
  const seq = ++fetchSeq;
  try {
    const server = await getQueue();
    if (seq !== fetchSeq || server.slugs.length === 0 || !isNewer(server.updated_at)) return;
    const index = Math.max(0, Math.min(server.slugs.length - 1, server.index));
    const copy: LocalQueue = { slugs: server.slugs, index, updatedAt: server.updated_at };
    if (get(player).playing) {
      local = copy;
      writeLocal();
      return;
    }
    const set = await getSet(server.slugs[index]);
    if (seq !== fetchSeq || get(player).playing) return;
    local = copy;
    writeLocal();
    resumeOffer.set({ slugs: server.slugs, index, title: set.title });
  } catch { /* offline or the set is gone: no offer */ }
}

export function startQueueSync(): void {
  if (started || typeof window === "undefined") return;
  started = true;
  local = readLocal();
  if (local && local.slugs.length > 0 && get(queue).slugs.length === 0) {
    queue.set({ slugs: local.slugs.slice(), index: Math.max(0, Math.min(local.slugs.length - 1, local.index)) });
  }
  onQueueChange(onChange);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void fetchServerQueue();
  });
  void fetchServerQueue();
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
