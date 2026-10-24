import { writable } from "svelte/store";

/** Pending-review discovery count for the nav badge; null until first loaded. */
export const pendingDiscoveries = writable<number | null>(null);
