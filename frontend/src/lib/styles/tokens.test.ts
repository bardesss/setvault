import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..", "..");
const STYLES = __dirname;

// Tokens read at runtime via getPropertyValue (waveform/playhead) rather than
// referenced with var(); allow them explicitly even if a stylesheet drops them.
const RUNTIME_TOKENS = new Set([
  "--waveform-played",
  "--waveform-unplayed",
  "--playhead",
]);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(svelte|css)$/.test(name)) out.push(p);
  }
  return out;
}

const files = walk(SRC);
const rel = (p: string) => relative(SRC, p).split(sep).join("/");

describe("theme tokens", () => {
  it("no undefined css custom properties", () => {
    const defined = new Set<string>(RUNTIME_TOKENS);
    for (const f of walk(STYLES)) {
      for (const m of readFileSync(f, "utf8").matchAll(/(--[\w-]+)\s*:/g)) defined.add(m[1]);
    }
    const undef: string[] = [];
    for (const f of files) {
      const text = readFileSync(f, "utf8");
      for (const m of text.matchAll(/var\(\s*(--[\w-]+)/g)) {
        if (!defined.has(m[1])) undef.push(`${rel(f)}: ${m[1]}`);
      }
    }
    expect(undef).toEqual([]);
  });

  it("no hardcoded #c33", () => {
    const bad = files.filter((f) => /#c33\b/i.test(readFileSync(f, "utf8"))).map(rel);
    expect(bad).toEqual([]);
  });
});
