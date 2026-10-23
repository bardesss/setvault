import { describe, expect, it, vi } from "vitest";

import { chooseStrategy, resolveAudio } from "./sw-strategy";

describe("resolveAudio", () => {
  // A tiny fake audio cache keyed by full URL.
  function fakeIo(cached: Record<string, string>, requestUrl: string, online: boolean) {
    const fetchNetwork = vi.fn(async () => {
      if (!online) throw new TypeError("Failed to fetch");
      return "network";
    });
    return {
      fetchNetwork,
      io: {
        matchExact: async () => cached[requestUrl],
        matchIgnoringSearch: async () => {
          const path = requestUrl.split("?")[0];
          const hit = Object.keys(cached).find((k) => k.split("?")[0] === path);
          return hit ? cached[hit] : undefined;
        },
        fetchNetwork,
      },
    };
  }

  it("serves the older copy offline when only a different ?v= is cached", async () => {
    const { io } = fakeIo(
      { "/api/sets/x/stream?v=0.0": "old copy" },
      "/api/sets/x/stream?v=-6.0",
      false,
    );
    expect(await resolveAudio(io)).toBe("old copy");
  });

  it("fetches the network when online and the exact URL is not cached", async () => {
    const { io, fetchNetwork } = fakeIo(
      { "/api/sets/x/stream?v=0.0": "old copy" },
      "/api/sets/x/stream?v=-6.0",
      true,
    );
    expect(await resolveAudio(io)).toBe("network");
    expect(fetchNetwork).toHaveBeenCalledOnce();
  });

  it("serves an exact match without touching the network", async () => {
    const { io, fetchNetwork } = fakeIo(
      { "/api/sets/x/stream?v=-6.0": "exact" },
      "/api/sets/x/stream?v=-6.0",
      true,
    );
    expect(await resolveAudio(io)).toBe("exact");
    expect(fetchNetwork).not.toHaveBeenCalled();
  });

  it("rethrows the network error when nothing is cached at all", async () => {
    const { io } = fakeIo({}, "/api/sets/x/stream?v=-6.0", false);
    await expect(resolveAudio(io)).rejects.toThrow("Failed to fetch");
  });
});

const PRECACHED = ["/", "/favicon.png"];

describe("chooseStrategy", () => {
  it("returns 'static' for SvelteKit build chunks", () => {
    expect(chooseStrategy("/_app/immutable/foo.js", PRECACHED)).toBe("static");
  });

  it("returns 'static' for /fonts/ and /icons/", () => {
    expect(chooseStrategy("/fonts/BricolageGrotesque-400.woff2", PRECACHED)).toBe("static");
    expect(chooseStrategy("/icons/icon-192.png", PRECACHED)).toBe("static");
  });

  it("returns 'static' for the manifest", () => {
    expect(chooseStrategy("/manifest.webmanifest", PRECACHED)).toBe("static");
  });

  it("returns 'static' for precached URLs", () => {
    expect(chooseStrategy("/", PRECACHED)).toBe("static");
    expect(chooseStrategy("/favicon.png", PRECACHED)).toBe("static");
  });

  it("returns 'audio' for /api/sets/<slug>/stream", () => {
    expect(chooseStrategy("/api/sets/seeded-set-abc123/stream", PRECACHED)).toBe("audio");
  });

  it("returns 'audio' for /api/sets/<slug>/stream?sig=... (signed URLs)", () => {
    // pathname doesn't include the query, but the matcher still must apply.
    expect(chooseStrategy("/api/sets/seeded-set-abc123/stream", PRECACHED)).toBe("audio");
  });

  it("returns 'api' for non-audio /api/ calls (network-first, offline fallback)", () => {
    expect(chooseStrategy("/api/sets/seeded-set/waveform", PRECACHED)).toBe("api");
    expect(chooseStrategy("/api/me/rss-tokens", PRECACHED)).toBe("api");
    expect(chooseStrategy("/api/health", PRECACHED)).toBe("api");
  });

  it("returns 'navigation' for SvelteKit page routes", () => {
    expect(chooseStrategy("/sets/some-slug", PRECACHED)).toBe("navigation");
    expect(chooseStrategy("/settings", PRECACHED)).toBe("navigation");
    expect(chooseStrategy("/embed/foo", PRECACHED)).toBe("navigation");
  });

  it("returns 'bypass' for admin API routes, 'api' for others", () => {
    expect(chooseStrategy("/api/admin/backup", PRECACHED)).toBe("bypass");
    expect(chooseStrategy("/api/admin/settings", PRECACHED)).toBe("bypass");
    expect(chooseStrategy("/api/sets", PRECACHED)).toBe("api");
  });
});
