import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";
import type { BackupList } from "#lib/api/backups.ts";

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/admin/backups");
  if (!response.ok) {
    throw error(response.status, "Failed to load backups");
  }
  return { backups: (await response.json()) as BackupList };
};
