/** Pure cache helpers for the service worker (unit-testable, no SW globals). */

// Unversioned on purpose: downloaded audio must survive deploys.
export const AUDIO_CACHE = "setvault-audio";
export const META_CACHE = "setvault-meta";
export const CAP_KEY = "/__setvault/cap";
export const DEFAULT_CAP_BYTES = 1024 * 1024 * 1024;

/**
 * Caches to delete on activate: everything not belonging to the current
 * version, except the persistent audio and meta caches. Old versioned audio
 * caches (`setvault-<v>-audio`) are dropped.
 */
export function cachesToDelete(keys: string[], currentVersionPrefix: string): string[] {
  return keys.filter(
    (k) => k !== AUDIO_CACHE && k !== META_CACHE && !k.startsWith(currentVersionPrefix),
  );
}

export async function loadCap(cache: Cache): Promise<number> {
  try {
    const res = await cache.match(CAP_KEY);
    if (!res) return DEFAULT_CAP_BYTES;
    const n = Number(await res.text());
    return Number.isFinite(n) && n > 0 ? n : DEFAULT_CAP_BYTES;
  } catch {
    return DEFAULT_CAP_BYTES;
  }
}

export async function saveCap(cache: Cache, bytes: number): Promise<void> {
  await cache.put(CAP_KEY, new Response(String(bytes)));
}
