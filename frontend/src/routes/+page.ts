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

export interface ActivityItem {
  kind: "set_published" | "discovery" | "job_failed";
  at: string;
  title: string;
  href: string;
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
      activity: [] as ActivityItem[],
    };
  }

  const [summaryRes, cont, recentBody, activity] = await Promise.all([
    fetch("/api/me/home-summary").then((r) => (r.ok ? r.json() : null)),
    fetch("/api/me/continue-listening").then((r) => (r.ok ? r.json() : [])),
    fetch("/api/sets?limit=12&sort=recent").then((r) => (r.ok ? r.json() : { items: [] })),
    fetch("/api/me/home-activity").then((r) => (r.ok ? r.json() : [])),
  ]);

  return {
    user: layout.user,
    homeSummary: summaryRes as HomeSummary | null,
    continueListening: cont as ContinueItem[],
    recent: (recentBody.items ?? []) as RecentSet[],
    activity: activity as ActivityItem[],
  };
};
