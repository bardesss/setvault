import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

/** One background job run (RQ ids repeat across runs; `id` is per run). */
export interface JobRow {
  id: string;
  rq_id: string;
  kind: string;
  status: string;
  progress_pct: number;
  message: string | null;
  result: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/admin/jobs");
  if (!response.ok) {
    throw error(response.status, "Failed to load jobs");
  }
  const body = (await response.json()) as { items: JobRow[] };
  return { jobs: body.items };
};
