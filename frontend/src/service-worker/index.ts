import { version } from "$app/env";
import { assets, immutable } from "$app/manifest";
import { self as sw } from "$app/service-worker";
import { chooseStrategy, resolveAudio } from "#lib/sw-strategy.ts";
import {
  AUDIO_CACHE,
  META_CACHE,
  cachesToDelete,
  loadCap,
  saveCap,
} from "#lib/sw-cache.ts";

const CACHE_VERSION = `setvault-${version}`;
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

// immutable = SvelteKit chunks; assets = everything under static/.
// $app/manifest paths are relative to the base path; the app is served from
// the root (see the "/service-worker.js" registration), so make them absolute
// to match the URL pathnames chooseStrategy() compares against.
const PRECACHE_URLS = [...immutable, ...assets].map(({ path }) => `/${path}`);

sw.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(STATIC_CACHE);
      await cache.addAll(PRECACHE_URLS);
      await sw.skipWaiting();
    })(),
  );
});

sw.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        cachesToDelete(keys, CACHE_VERSION).map((k) => caches.delete(k)),
      );
      await sw.clients.claim();
    })(),
  );
});

sw.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== sw.location.origin) return;  // skip cross-origin

  const strategy = chooseStrategy(url.pathname, PRECACHE_URLS);
  if (strategy === "bypass") return;

  if (strategy === "static") {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
  } else if (strategy === "audio") {
    event.respondWith(audioCacheFirst(request));
  } else {
    // "navigation" + "api": network-first. Online always wins (auth/data stay
    // fresh); the runtime cache is an offline fallback only. As an SPA, page
    // content comes from /api GETs, so they need the same offline fallback the
    // page documents already get — otherwise an offline reload renders an
    // empty shell.
    event.respondWith(networkFirst(request, RUNTIME_CACHE));
  }
});

async function cacheFirst(request: Request, cacheName: string): Promise<Response> {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}

async function audioCacheFirst(request: Request): Promise<Response> {
  const cache = await caches.open(AUDIO_CACHE);
  // Exact match, then network, then (offline only) an older copy of the same
  // set under a different ?v= gain tag. The order lives in resolveAudio().
  return resolveAudio<Response>({
    matchExact: () => cache.match(request),
    matchIgnoringSearch: () => cache.match(request, { ignoreSearch: true }),
    fetchNetwork: async () => {
      const response = await fetch(request);
      // Only full (200) responses can be stored. `<audio>` elements issue Range
      // requests, which the server answers with 206 Partial Content — and
      // Cache.put() rejects a 206, which would reject this handler and fail the
      // media element with net::ERR_FAILED. Pass partial responses straight
      // through; the explicit "cache this set offline" full GET (200) still caches.
      if (response.status === 200) {
        // A storage failure must not turn a good network response into an
        // "offline" fallback to an older copy.
        try {
          await cache.put(request, response.clone());
          await enforceAudioCap();
        } catch {
          // quota or cache error: serve the fresh response uncached
        }
      }
      return response;
    },
  });
}

async function networkFirst(request: Request, cacheName: string): Promise<Response> {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok && isCacheable(response)) {
      await cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
}

// Honour the server's intent: never persist a response the backend marks
// non-cacheable (no-store / no-cache / private). Lets sensitive endpoints
// (e.g. /api/me/rss-tokens) opt out of the offline runtime cache.
function isCacheable(response: Response): boolean {
  const cc = response.headers.get("Cache-Control");
  if (!cc) return true;
  return !/(?:^|[\s,])(?:no-store|no-cache|private)(?:[\s,;]|$)/i.test(cc);
}

// Audio-cap state. Main thread sends `{type: "set-cap", bytes}` via
// postMessage. The cap is persisted in the meta cache (a SW can be killed and
// restarted at any time) and read lazily; default is 1 GB.

sw.addEventListener("message", (event) => {
  const data = event.data as { type?: string; bytes?: number } | null;
  if (data?.type === "set-cap" && typeof data.bytes === "number") {
    // Enforce immediately so the admin's new cap kicks in without waiting
    // for the next audio fetch. Posts back when done so callers can await
    // via `MessageChannel`.
    const port = event.ports?.[0];
    const work = (async () => {
      await saveCap(await caches.open(META_CACHE), data.bytes as number);
      await enforceAudioCap();
    })().then(() => {
      if (port) port.postMessage({ type: "cap-enforced" });
    });
    event.waitUntil?.(work);
  }
});

async function enforceAudioCap(): Promise<void> {
  const cap = await loadCap(await caches.open(META_CACHE));
  const cache = await caches.open(AUDIO_CACHE);
  const keys = await cache.keys();
  let total = 0;
  const sized: { req: Request; size: number }[] = [];
  for (const req of keys) {
    const res = await cache.match(req);
    if (!res) continue;
    const blob = await res.clone().blob();
    sized.push({ req, size: blob.size });
    total += blob.size;
  }
  // Cache iteration order is roughly insertion-order; evict oldest first.
  while (total > cap && sized.length > 0) {
    const oldest = sized.shift()!;
    await cache.delete(oldest.req);
    total -= oldest.size;
  }
}
