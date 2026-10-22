// Plain-English "Last result" for the admin Wanted page (Phase 7D).

export interface WantedEvent {
  outcome: string;
  reason: string | null;
  created_at: string;
}

const REASONS: Record<string, string> = {
  "different audio": "Rejected: different audio",
  "not better": "Rejected: not better",
  "not owner": "Rejected: not the set's owner",
  "upgrades off": "Skipped: upgrades are off",
  "target unavailable": "Skipped: set unavailable",
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
export function wantedResult(ev: WantedEvent | null, lastSearchedAt: string | null): string {
  if (ev && !isCurrent(ev, lastSearchedAt)) ev = null;
  if (!ev) return lastSearchedAt ? "No better copy found" : "None yet";
  if (ev.outcome === "upgraded") return "Upgraded";
  if (ev.outcome === "merged") return "Merged";
  const reason = ev.reason ?? "";
  if (reason.startsWith("rip failed") || reason.startsWith("probe failed")) {
    return "Download failed";
  }
  if (REASONS[reason]) return REASONS[reason];
  return reason ? `Rejected: ${reason}` : "Rejected";
}

const SEARCH_REFUSED: Record<string, string> = {
  "not fingerprinted yet": "Not fingerprinted yet — run the backfill on the Quality tab",
  "quality not measured yet": "Quality not measured yet — run the backfill on the Quality tab",
  "upgrades are off for this set": "Upgrades are off for this set",
  "set already meets the quality cutoff": "Already meets the quality cutoff",
  "set is a duplicate of another set": "A duplicate of another set — search its original instead",
};

/** Why Search now was refused (a 409), as that row's status. */
export function searchRefusal(detail: string): string {
  const known = SEARCH_REFUSED[detail];
  if (known) return known;
  return detail ? detail.charAt(0).toUpperCase() + detail.slice(1) : "Can't search this set now";
}

/** A timestamp in the app's UI language (svelte-i18n `$locale`, default "en") and the browser's time zone. */
export function fmtLocalDateTime(iso: string | null, locale?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(locale || "en", { dateStyle: "medium", timeStyle: "short" });
}
