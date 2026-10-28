/** Finds user-visible text written straight into Svelte markup (not through
 *  `$_()`). A heuristic for the i18n guard test, not a parser: it strips
 *  script/style blocks, comments and `{…}` expressions, then looks at text
 *  between tags and at text-bearing attributes. */

// Attributes and component props whose literal value is shown to people.
const TEXT_ATTRS = [
  "aria-label", "title", "placeholder", "alt", "label", "heading",
  "subtitle", "hint", "message", "description", "confirmLabel", "emptyText",
];

// Text that is fine to hardcode: the brand, units, symbols.
const ALLOWED = [/\bSetVault\b/gi, /\b(?:KB|MB|GB|TB|dB|LUFS|kbps|kHz|Hz)\b/g, /\b[BKMGT]\b/g];

/** Replaces every `{…}` (nested braces included, quotes respected) with a
 *  space-padded marker so text around it stays separate. */
function stripExpressions(src: string): string {
  let out = "";
  let depth = 0;
  let quote: string | null = null;
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (depth === 0) {
      if (c === "{") { depth = 1; out += " \u0000 "; }
      else out += c;
      continue;
    }
    if (quote) {
      if (c === "\\") { i++; continue; }
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") quote = c;
    else if (c === "{") depth++;
    else if (c === "}") depth--;
  }
  return out;
}

function lineOf(src: string, index: number): number {
  let n = 1;
  for (let i = 0; i < index; i++) if (src.charCodeAt(i) === 10) n++;
  return n;
}

function visible(text: string): boolean {
  let t = text;
  for (const re of ALLOWED) t = t.replace(re, "");
  return /\p{L}/u.test(t);
}

export interface Hit { line: number; text: string }

export function scanMarkup(svelte: string): Hit[] {
  // Blank out non-markup regions but keep their newlines, so lines still match.
  const blank = (m: string) => m.replace(/[^\n]/g, " ");
  let src = svelte
    .replace(/<script[\s\S]*?<\/script>/g, blank)
    .replace(/<style[\s\S]*?<\/style>/g, blank)
    .replace(/<!--[\s\S]*?-->/g, blank);
  src = stripExpressions(src);
  const hits: Hit[] = [];

  const attrRe = new RegExp(String.raw`\s(?:${TEXT_ATTRS.join("|")})="([^"]*)"`, "g");
  for (const m of src.matchAll(attrRe)) {
    if (visible(m[1].replace(/\u0000/g, ""))) {
      hits.push({ line: lineOf(src, m.index!), text: m[0].trim() });
    }
  }

  // Text nodes: whatever sits between one tag's `>` and the next `<`.
  const noTags = src.replace(/<[^>]*>/g, (tag) => "\u0001" + blank(tag).slice(1));
  for (const m of noTags.matchAll(/\u0001([^\u0001]*)/g)) {
    const body = m[1].replace(/\u0000/g, " ");
    if (!visible(body)) continue;
    const offset = m.index! + 1 + body.search(/\S/);
    hits.push({ line: lineOf(src, offset), text: body.trim().replace(/\s+/g, " ").slice(0, 80) });
  }
  return hits;
}
