import type { LookupRow } from "./api/lookup.ts";

/** Next highlight index with wrap-around; -1 when there is nothing to highlight. */
export function nextIndex(current: number, delta: 1 | -1, length: number): number {
  if (length <= 0) return -1;
  if (current < 0) return delta === 1 ? 0 : length - 1;
  return (current + delta + length) % length;
}

/** Whether to show a "create <q>" row: non-blank and no casefold-equal name already listed or selected. */
export function offerCreate(
  q: string,
  results: LookupRow[],
  selected: LookupRow[],
): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return false;
  const same = (r: LookupRow) => r.name.trim().toLowerCase() === needle;
  return !results.some(same) && !selected.some(same);
}

/** Returns a copy of `list` with the item at `from` moved to `to`; out-of-range moves are no-ops. */
export function moveItem<T>(list: T[], from: number, to: number): T[] {
  const out = list.slice();
  if (from < 0 || from >= out.length || to < 0 || to >= out.length) return out;
  const [item] = out.splice(from, 1);
  out.splice(to, 0, item);
  return out;
}
