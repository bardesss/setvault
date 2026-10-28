import { error } from "@sveltejs/kit";
import { get } from "svelte/store";
import { _ } from "svelte-i18n";
import { setupI18n } from "#lib/i18n/index.ts";
import type { PageLoad } from "./$types";
import type { BackupList } from "#lib/api/backups.ts";

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/admin/backups");
  if (!response.ok) {
    await setupI18n();
    throw error(response.status, get(_)("admin.backups.load_failed"));
  }
  return { backups: (await response.json()) as BackupList };
};
