import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SUPPORTED_LOCALES,
  normalizeLocale,
  pickStartLocale,
  readCachedLocale,
  writeCachedLocale,
} from "./locale.ts";

describe("normalizeLocale", () => {
  it("reduces a region tag to the supported primary language", () => {
    expect(normalizeLocale("nl-NL")).toBe("nl");
    expect(normalizeLocale("nl_BE")).toBe("nl");
    expect(normalizeLocale("EN")).toBe("en");
  });
  it("rejects unsupported and empty values", () => {
    expect(normalizeLocale("XX")).toBeNull();
    expect(normalizeLocale("ja-JP")).toBeNull();
    expect(normalizeLocale("de")).toBeNull();
    expect(normalizeLocale("")).toBeNull();
    expect(normalizeLocale(null)).toBeNull();
    expect(normalizeLocale(undefined)).toBeNull();
  });
});

describe("pickStartLocale", () => {
  it("prefers the cached choice", () => {
    expect(pickStartLocale({ cached: "nl", navigator: "en-US" })).toBe("nl");
  });
  it("ignores a stale cached value and uses the browser language", () => {
    expect(pickStartLocale({ cached: "xx", navigator: "nl-BE" })).toBe("nl");
  });
  it("falls back to English", () => {
    expect(pickStartLocale({ cached: null, navigator: "ja" })).toBe("en");
    expect(pickStartLocale({ cached: null, navigator: null })).toBe("en");
  });
});

describe("locale cache", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads null when localStorage throws", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => { throw new Error("blocked"); },
    });
    expect(readCachedLocale()).toBeNull();
  });

  it("writes and clears the cached choice", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    });
    writeCachedLocale("nl");
    expect(readCachedLocale()).toBe("nl");
    writeCachedLocale(null);
    expect(readCachedLocale()).toBeNull();
  });

  it("swallows a throwing setItem", () => {
    vi.stubGlobal("localStorage", {
      setItem: () => { throw new Error("quota"); },
    });
    expect(() => writeCachedLocale("nl")).not.toThrow();
  });
});

describe("supported locales", () => {
  it("match the backend list", () => {
    const py = readFileSync(
      new URL("../../../../packages/core/src/setvault_core/locales.py", import.meta.url),
      "utf8",
    );
    const tuple = py.match(/SUPPORTED_LOCALES[^=]*=\s*\(([^)]*)\)/);
    expect(tuple).not.toBeNull();
    const backend = [...tuple![1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect(backend).toEqual([...SUPPORTED_LOCALES]);
  });
});
