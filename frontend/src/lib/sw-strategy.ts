/**
 * Service-worker route → strategy selector.
 *
 * Extracted from `service-worker.ts` so the routing logic can be unit-tested
 * without spinning up an actual SW. The SW imports this and dispatches on
 * the strategy name.
 */

export type Strategy =
  | "static"        // cache-first; long-lived
  | "audio"         // cache-first with cap enforcement
  | "api"           // network-first; fresh online, cached fallback offline
  | "navigation"    // network-first, falls back to runtime cache
  | "bypass";       // don't touch this request

const AUDIO_RE = /^\/api\/sets\/[^/]+\/(stream|audio\.opus)(\?|$)/;

/**
 * What the audio strategy does for one request, as a decision order:
 * exact cache match, then the network, then (only if the network failed) a
 * match that ignores the query string. The stream URL carries `?v=<gain>`, so
 * a re-gained set is a new resource online; an offline phone keeps playing its
 * older copy instead of failing.
 */
export interface AudioIo<R> {
  matchExact: () => Promise<R | undefined>;
  matchIgnoringSearch: () => Promise<R | undefined>;
  fetchNetwork: () => Promise<R>;
}

export async function resolveAudio<R>(io: AudioIo<R>): Promise<R> {
  const exact = await io.matchExact();
  if (exact) return exact;
  try {
    return await io.fetchNetwork();
  } catch (err) {
    const older = await io.matchIgnoringSearch();
    if (older) return older;
    throw err;
  }
}

export function chooseStrategy(
  pathname: string,
  precacheUrls: ReadonlyArray<string> = [],
): Strategy {
  // Precached SvelteKit build chunks + static files.
  if (precacheUrls.includes(pathname)) return "static";
  if (pathname.startsWith("/_app/")) return "static";
  if (pathname.startsWith("/fonts/")) return "static";
  if (pathname.startsWith("/icons/")) return "static";
  if (pathname === "/manifest.webmanifest") return "static";

  // Audio stream is cache-first under an admin-configurable cap.
  if (AUDIO_RE.test(pathname)) return "audio";

  // Admin responses (backup dumps, settings) must never touch a cache.
  if (pathname.startsWith("/api/admin/")) return "bypass";

  // Every other /api/ call (including waveform JSON) is network-first: fresh
  // when online, served from the runtime cache when offline so SPA pages still
  // render after a first online load.
  if (pathname.startsWith("/api/")) return "api";

  // Anything else is a SvelteKit page navigation - network-first.
  return "navigation";
}
