/**
 * Offline audio cache state.
 *
 * The service worker (see `src/service-worker/index.ts`) does the actual caching
 * and quota enforcement. This store wraps the read side:
 *
 *  - The user-configured cap lives in localStorage so it survives reloads.
 *  - The widget polls usage via `navigator.storage.estimate()` and a Cache
 *    API walk.
 *  - `setCap()` updates localStorage AND posts the new cap to the SW so
 *    eviction kicks in immediately for the next audio fetch.
 */
import { browser } from "$app/env";
import { writable } from "svelte/store";

export interface OfflineState {
  capBytes: number;
  usedBytes: number;
  quotaBytes: number | null;  // origin-wide quota from navigator.storage
}

const DEFAULT_CAP_BYTES = 1024 * 1024 * 1024;  // 1 GB
const LOCAL_STORAGE_KEY = "setvault.offlineCapBytes";

function loadCap(): number {
  if (!browser) return DEFAULT_CAP_BYTES;
  const raw = localStorage.getItem(LOCAL_STORAGE_KEY);
  if (!raw) return DEFAULT_CAP_BYTES;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : DEFAULT_CAP_BYTES;
}

export const offline = writable<OfflineState>({
  capBytes: loadCap(),
  usedBytes: 0,
  quotaBytes: null,
});

async function findAudioCache(): Promise<Cache | null> {
  if (!browser || !("caches" in self)) return null;
  const names = await caches.keys();
  // The SW's audio cache is the unversioned `setvault-audio`; the suffix match
  // also finds legacy `setvault-<version>-audio` caches, freshest last.
  const audioName = names
    .filter((n) => n.endsWith("-audio"))
    .sort()
    .pop();
  if (!audioName) return null;
  return caches.open(audioName);
}

export async function refreshUsage(): Promise<void> {
  if (!browser) return;
  let used = 0;
  try {
    const cache = await findAudioCache();
    if (cache) {
      const keys = await cache.keys();
      for (const req of keys) {
        const res = await cache.match(req);
        if (!res) continue;
        const blob = await res.clone().blob();
        used += blob.size;
      }
    }
  } catch {
    // best-effort; widget just shows 0
  }
  let quota: number | null = null;
  try {
    if ("storage" in navigator && navigator.storage.estimate) {
      const est = await navigator.storage.estimate();
      quota = est.quota ?? null;
    }
  } catch {
    /* best-effort */
  }
  offline.update((s) => ({ ...s, usedBytes: used, quotaBytes: quota }));
}

/** Re-send the stored cap to the active SW (boot, controllerchange). */
export function postStoredCap(): void {
  if (!browser) return;
  try {
    navigator.serviceWorker?.controller?.postMessage({
      type: "set-cap",
      bytes: loadCap(),
    });
  } catch {
    /* SW not active yet */
  }
}

export function setCap(bytes: number): void {
  if (browser) {
    try {
      localStorage.setItem(LOCAL_STORAGE_KEY, String(bytes));
    } catch {
      /* private mode or quota — fall back to in-memory */
    }
    try {
      navigator.serviceWorker?.controller?.postMessage({ type: "set-cap", bytes });
    } catch {
      /* SW not active yet; the cap takes effect on next reload */
    }
  }
  offline.update((s) => ({ ...s, capBytes: bytes }));
}

// Drop every user-scoped cache (runtime API/page data + downloaded audio) so a
// logout can't serve the prior session's data to the next user on a shared
// browser. Static build chunks are not user-scoped and are left intact.
export async function clearScopedCaches(): Promise<void> {
  if (!browser || !("caches" in self)) return;
  const names = await caches.keys();
  await Promise.all(
    names
      .filter((n) => n.endsWith("-runtime") || n.endsWith("-audio"))
      .map((n) => caches.delete(n)),
  );
  offline.update((s) => ({ ...s, usedBytes: 0 }));
}

export async function clearAudioCache(): Promise<void> {
  if (!browser) return;
  const cache = await findAudioCache();
  if (!cache) return;
  const keys = await cache.keys();
  await Promise.all(keys.map((k) => cache.delete(k)));
  await refreshUsage();
}
