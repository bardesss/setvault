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

/** What the last upgrade attempt on a set came to. With no attempt on
 * record, a set that has been searched simply had no better copy. */
export function wantedResult(ev: WantedEvent | null, lastSearchedAt: string | null): string {
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

/** A timestamp in the browser's locale and time zone. */
export function fmtLocalDateTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
