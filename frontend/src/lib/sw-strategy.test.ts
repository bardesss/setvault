import { describe, expect, it } from "vitest";

import { chooseStrategy } from "./sw-strategy";

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
