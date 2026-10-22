import type { PageLoad } from "./$types";

interface HomeSummary {
  sets_count: number;
  tracks_resolved_count: number;
  tracks_needing_ids_count: number;
  audio_bytes: number;
  deltas_window_days: number;
  sets_delta: number;
  tracks_resolved_delta: number;
  tracks_needing_ids_delta: number;
}

interface ContinueItem {
  slug: string;
  title: string;
  position_seconds: number;
  duration_seconds: number | null;
}

interface RecentSet {
  slug: string;
  title: string;
  artists?: Array<{ name: string }>;
  venue?: { name: string } | null;
  date?: string | null;
  created_at?: string;
  [k: string]: unknown;
}

export const load: PageLoad = async ({ fetch, parent }) => {
  const layout = await parent();
  if (!layout.user) {
    return {
      user: null,
      homeSummary: null as HomeSummary | null,
      continueListening: [] as ContinueItem[],
      recent: [] as RecentSet[],
    };
  }

  const [summaryRes, cont, recentBody] = await Promise.all([
    fetch("/api/me/home-summary").then((r) => (r.ok ? r.json() : null)),
    fetch("/api/me/continue-listening").then((r) => (r.ok ? r.json() : [])),
    fetch("/api/sets?limit=12&sort=recent").then((r) => (r.ok ? r.json() : { items: [] })),
  ]);

  return {
    user: layout.user,
    homeSummary: summaryRes as HomeSummary | null,
    continueListening: cont as ContinueItem[],
    recent: (recentBody.items ?? []) as RecentSet[],
  };
};
