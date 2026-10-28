import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { IntlMessageFormat } from "intl-messageformat";
import { describe, expect, it } from "vitest";
import en from "./locales/en.json";
import nl from "./locales/nl.json";
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

type Ast = ReturnType<IntlMessageFormat["getAst"]>;

/** Variable names a message uses, plural/select branches included. */
function argNames(ast: Ast, out = new Set<string>()): Set<string> {
  for (const el of ast as Array<{ value?: unknown; options?: Record<string, { value: Ast }>; children?: Ast }>) {
    if (el.options) for (const opt of Object.values(el.options)) argNames(opt.value, out);
    if (el.children) argNames(el.children, out);
    if (typeof el.value === "string" && "type" in el && (el as { type: number }).type !== 0) {
      out.add(el.value);
    }
  }
  return out;
}

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

/** nl values that may equal the English one, because Dutch uses the same
 *  word (or it's a brand/technical token). Keep this short. */
const IDENTICAL_BY_DESIGN = new Set<string>([
  // Same word in Dutch UI
  "settings.tabs.offline", "library.filters", "library.tag",
  "nav.home", "nav.downloads", "home.recent_meta",
  "feeds.recent", "feeds.ok", "admin.providers.state_on",
  "admin.quality.tier_ok", "admin.storage.health.ok", "admin.providers.test_result",
  "admin.tasks.col_interval", "admin.system.build", "catalog.website",
  "catalog.bio", "topbar.account", "pwa.cache.heading",
  "admin.layout.release_notes", "admin.webhooks.headers", "admin.jobs.col_status",
  "admin.webhooks.col_status", "admin.users.col_status", "admin.health.col_status",
  "admin.tasks.col_status", "discoveries.col_status",
  // Glossary terms kept in Dutch (set, track, tracklist, tag, monitor, provider, webhook, upload)
  "home.summary_sets", "playlists.items", "browse.sets_count",
  "search.group_sets", "admin.wanted.col_set", "admin.drafts.col_set",
  "admin.storage.col_sets", "admin.system.sets", "catalog.sets",
  "browse.track_chip", "browse.track_chip_artist", "embed.track_fallback",
  "tracklist.heading", "set.tags_label", "set_edit.tags",
  "monitors.admin_title", "monitors.monitor", "admin.providers.kind",
  "admin.layout.tab_providers", "admin.health.providers", "admin.layout.tab_webhooks",
  "url_rip.tab_upload",
  // Audio and DJ jargon
  "admin.quality.tier_lossless", "sources.quality.lossless", "set.artist_role.b2b",
  "set_edit.type.b2b",
  // Technical tokens and protocol names
  "tracklist.tab_url", "admin.webhooks.col_url", "url_rip.tab_label",
  "admin.email.sec_starttls", "admin.email.sec_ssl", "admin.recycle.col_slug",
  "admin.catalog.col_slug",
  // Unit abbreviations that read the same
  "admin.jobs.duration_s", "admin.jobs.duration_m", "admin.tasks.interval_s",
  "admin.tasks.interval_m", "admin.tasks.interval_d", "cards.duration_m",
]);

describe("Dutch translation", () => {
  it("nl has exactly en's key set", () => {
    const missing = Object.keys(EN).filter((k) => !(k in NL));
    const extra = Object.keys(NL).filter((k) => !(k in EN));
    expect({ missing, extra }).toEqual({ missing: [], extra: [] });
  });

  it("every nl value is non-empty and translated", () => {
    const untranslated = Object.keys(EN).filter(
      (k) => k in NL && (!NL[k].trim() || (NL[k] === EN[k] && !IDENTICAL_BY_DESIGN.has(k))),
    );
    expect(untranslated).toEqual([]);
  });

  it("nl keeps every placeholder of en", () => {
    const names = (msg: string, loc: string) =>
      [...argNames(new IntlMessageFormat(msg, loc).getAst())].sort().join(",");
    const diff = Object.keys(EN).filter((k) => k in NL && names(EN[k], "en") !== names(NL[k], "nl"));
    expect(diff).toEqual([]);
  });

  it("plural messages render for 0, 1 and 5 in en and nl", () => {
    const plural = Object.keys(EN).filter((k) => /,\s*plural\s*,/.test(EN[k]));
    expect(plural.length).toBeGreaterThan(0);
    for (const k of plural) {
      for (const [loc, msgs] of [["en", EN], ["nl", NL]] as const) {
        const fmt = new IntlMessageFormat(msgs[k], loc);
        const vars = [...argNames(fmt.getAst())];
        for (const n of [0, 1, 5]) {
          const values = Object.fromEntries(vars.map((v) => [v, n]));
          const out = String(fmt.format(values));
          expect(out, `${loc} ${k} (${n})`).not.toMatch(/[{}]/);
          // "other" branches show the count (an "=0" branch may word it).
          if (n === 5 && msgs[k].includes("#")) expect(out, `${loc} ${k}`).toContain("5");
        }
      }
    }
  });
});

describe("hardcoded markup", () => {
  it("no .svelte file writes user-visible text outside $_()", () => {
    const hits: Record<string, string[]> = {};
    for (const f of walk(SRC, [".svelte"])) {
      const found = scanMarkup(readFileSync(f, "utf8"));
      if (found.length) hits[rel(f)] = found.map((h) => `${h.line}: ${h.text}`);
    }
    expect(hits).toEqual({});
  });
});
