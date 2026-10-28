import { error } from "@sveltejs/kit";
import { get } from "svelte/store";
import { _ } from "svelte-i18n";
import { setupI18n } from "#lib/i18n/index.ts";
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
    await setupI18n();
    throw error(response.status, get(_)("admin.jobs.load_failed"));
  }
  const body = (await response.json()) as { items: JobRow[] };
  return { jobs: body.items };
};
