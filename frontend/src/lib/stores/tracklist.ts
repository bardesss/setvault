import { writable } from "svelte/store";
import type { TracklistEntry } from "#lib/api/tracklist.ts";

interface TracklistState {
  entries: TracklistEntry[];
  loading: boolean;
  error: string | null;
}

export const tracklist = writable<TracklistState>({
  entries: [],
  loading: false,
  error: null,
});

export function setEntries(entries: TracklistEntry[]): void {
  tracklist.set({ entries, loading: false, error: null });
}

export function upsertEntry(entry: TracklistEntry): void {
  tracklist.update((s) => {
    const idx = s.entries.findIndex((e) => e.id === entry.id);
    const next = [...s.entries];
    if (idx >= 0) next[idx] = entry;
    else next.push(entry);
    next.sort((a, b) => a.position - b.position);
    return { ...s, entries: next };
  });
}

export function removeEntry(id: string): void {
  tracklist.update((s) => ({
    ...s,
    entries: s.entries.filter((e) => e.id !== id),
  }));
}
