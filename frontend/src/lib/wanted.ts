// Plain-English "Last result" for the admin Wanted page (Phase 7D). The
// labels live in the locale files under `wanted.*`; pass svelte-i18n's `$_`
// as `t` to get them in the UI language (English when left out).
import { IntlMessageFormat } from "intl-messageformat";
import en from "./i18n/locales/en.json";

/** svelte-i18n's `$_`, or anything shaped like it. */
export type Translate = (key: string, opts?: { values?: Record<string, string | number> }) => string;

type Tree = { [k: string]: string | Tree };

/** English from en.json, for callers that don't pass a translator. */
const english: Translate = (key, opts) => {
  let node: string | Tree | undefined = en as Tree;
  for (const part of key.split(".")) node = typeof node === "object" ? node[part] : undefined;
  if (typeof node !== "string") return key;
  return String(new IntlMessageFormat(node, "en").format(opts?.values));
};

export interface WantedEvent {
  outcome: string;
  reason: string | null;
  created_at: string;
}

const REASONS: Record<string, string> = {
  "different audio": "wanted.reason.different_audio",
  "not better": "wanted.reason.not_better",
  "not owner": "wanted.reason.not_owner",
  "upgrades off": "wanted.reason.upgrades_off",
  "target unavailable": "wanted.reason.target_unavailable",
};

// The search that writes an event stamps the set's last search a moment
// later; an event older than that by more than this belongs to an earlier
// search.
const EVENT_SLACK_MS = 60_000;

/** Whether `ev` came from the set's latest search. A search that finds
 * nothing writes no event, only bumps the last-search time, so an older
 * event is stale. */
function isCurrent(ev: WantedEvent, lastSearchedAt: string | null): boolean {
  if (!lastSearchedAt) return true;
  const at = new Date(ev.created_at).getTime();
  const searched = new Date(lastSearchedAt).getTime();
  if (Number.isNaN(at) || Number.isNaN(searched)) return true;
  return at >= searched - EVENT_SLACK_MS;
}

/** What the last upgrade attempt on a set came to. With no attempt on
 * record since the latest search, a set that has been searched simply had
 * no better copy. */
export function wantedResult(
  ev: WantedEvent | null,
  lastSearchedAt: string | null,
  t: Translate = english,
): string {
  if (ev && !isCurrent(ev, lastSearchedAt)) ev = null;
  if (!ev) return t(lastSearchedAt ? "wanted.result.no_better_copy" : "wanted.result.none_yet");
  if (ev.outcome === "upgraded") return t("wanted.result.upgraded");
  if (ev.outcome === "merged") return t("wanted.result.merged");
  const reason = ev.reason ?? "";
  if (reason.startsWith("rip failed") || reason.startsWith("probe failed")) {
    return t("wanted.result.download_failed");
  }
  if (REASONS[reason]) return t(REASONS[reason]);
  // An unknown reason is server text: shown as-is.
  return reason ? t("wanted.result.rejected_reason", { values: { reason } }) : t("wanted.result.rejected");
}

const SEARCH_REFUSED: Record<string, string> = {
  "not fingerprinted yet": "wanted.refusal.not_fingerprinted",
  "quality not measured yet": "wanted.refusal.not_measured",
  "upgrades are off for this set": "wanted.refusal.upgrades_off",
  "set already meets the quality cutoff": "wanted.refusal.meets_cutoff",
  "set is a duplicate of another set": "wanted.refusal.duplicate",
};

/** Why Search now was refused (a 409), as that row's status. An unknown
 *  server detail is shown as-is, capitalised. */
export function searchRefusal(detail: string, t: Translate = english): string {
  const known = SEARCH_REFUSED[detail];
  if (known) return t(known);
  return detail ? detail.charAt(0).toUpperCase() + detail.slice(1) : t("wanted.refusal.fallback");
}

// Kept here for existing importers.
export { fmtLocalDateTime } from "#lib/format.ts";
