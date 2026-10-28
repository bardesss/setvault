import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { IntlMessageFormat } from "intl-messageformat";
import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import nl from "./locales/nl.json";
import baseline from "./hardcoded-baseline.json";
import { scanMarkup } from "./markup-scan.ts";

const SRC = fileURLToPath(new URL("../../", import.meta.url));

/** Keys built at run time with a template string: `$_(\`x.${k}\`)`. Each
 *  prefix must have at least one key under it in en.json. */
const DYNAMIC_KEY_PREFIXES = [
  "admin.jobs.status.",
  "admin.storage.health.",
  "discoveries.status_",
  "home.activity.",
  "set_edit.type.",
  "settings.notification_kinds.",
  "sources.quality.",
  "url_rip.status.",
];

type Tree = { [k: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(tree)) {
    if (typeof v === "string") out[prefix + k] = v;
    else Object.assign(out, flatten(v, `${prefix}${k}.`));
  }
  return out;
}

function walk(dir: string, exts: string[]): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return walk(p, exts);
    if (/\.test\.ts$/.test(name)) return [];
    return exts.some((e) => name.endsWith(e)) ? [p] : [];
  });
}

const rel = (p: string) => relative(SRC, p).split(sep).join("/");
const EN = flatten(en as Tree);
const NL = flatten(nl as Tree);

describe("translation keys", () => {
  it("every literal $_ key exists in en.json", () => {
    const missing: string[] = [];
    const call = /\$(?:_|t)\(\s*(["'])([^"']+)\1/g;
    for (const file of walk(SRC, [".svelte", ".ts"])) {
      const src = readFileSync(file, "utf8");
      for (const m of src.matchAll(call)) {
        if (!(m[2] in EN)) missing.push(`${rel(file)}: ${m[2]}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("dynamic key prefixes exist", () => {
    for (const prefix of DYNAMIC_KEY_PREFIXES) {
      expect(Object.keys(EN).some((k) => k.startsWith(prefix)), prefix).toBe(true);
    }
  });

  it("en and nl messages parse as ICU", () => {
    const bad: string[] = [];
    for (const [loc, msgs] of [["en", EN], ["nl", NL]] as const) {
      for (const [k, msg] of Object.entries(msgs)) {
        try {
          new IntlMessageFormat(msg, loc);
        } catch (e) {
          bad.push(`${loc} ${k}: ${(e as Error).message}`);
        }
      }
    }
    expect(bad).toEqual([]);
  });
});

describe("hardcoded markup", () => {
  const files = walk(SRC, [".svelte"]);
  const hits = new Map<string, string[]>();
  for (const f of files) {
    const found = scanMarkup(readFileSync(f, "utf8"));
    if (found.length) hits.set(rel(f), found.map((h) => `${h.line}: ${h.text}`));
  }
  const allowed = new Set<string>(baseline.files);

  it("no hardcoded text outside the baseline", () => {
    const offenders = [...hits].filter(([f]) => !allowed.has(f));
    expect(Object.fromEntries(offenders)).toEqual({});
  });

  it("the baseline only lists files that still need work", () => {
    const done = [...allowed].filter((f) => !hits.has(f));
    expect(done, "remove these from hardcoded-baseline.json").toEqual([]);
  });
});
