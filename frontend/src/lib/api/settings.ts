import { api } from "./client";

export interface AdminSettings {
  audit_retention_days: number;
  monitors_allow_all_users: boolean;
  monitor_interval_seconds: number;
  single_user_auto_login: boolean;
  quality_tiers_order: string[];
  quality_cutoff: string;
  auto_upgrades_enabled: boolean;
  upgrade_search_schedule: "daily" | "weekly" | "off";
}

export function getSettings(): Promise<AdminSettings> {
  return api<AdminSettings>("/api/admin/settings");
}

export function updateSettings(
  patch: Partial<AdminSettings>,
): Promise<AdminSettings> {
  return api<AdminSettings>("/api/admin/settings", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}
