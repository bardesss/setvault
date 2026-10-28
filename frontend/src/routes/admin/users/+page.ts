import { error } from "@sveltejs/kit";
import { get } from "svelte/store";
import { _ } from "svelte-i18n";
import { setupI18n } from "#lib/i18n/index.ts";
import type { PageLoad } from "./$types";

export interface AdminUser {
  id: string;
  email: string;
  username: string;
  display_name: string;
  role: string;
  disabled_at: string | null;
}

export const load: PageLoad = async ({ fetch }) => {
  const response = await fetch("/api/users");
  if (!response.ok) {
    await setupI18n();
    throw error(response.status, get(_)("admin.users.load_failed"));
  }
  const body = (await response.json()) as { items: AdminUser[] };
  return { users: body.items };
};
