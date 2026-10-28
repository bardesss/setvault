import { error } from "@sveltejs/kit";
import { get } from "svelte/store";
import { _ } from "svelte-i18n";
import { setupI18n } from "#lib/i18n/index.ts";
import type { PageLoad } from "./$types";

export interface SystemInfo {
  version: string;
  user_count: number;
  set_count: number;
  env: Record<string, string>;
}

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/admin/system");
  if (!response.ok) {
    await setupI18n();
    throw error(response.status, get(_)("admin.system.load_failed"));
  }
  const info = (await response.json()) as SystemInfo;
  return { info };
};
