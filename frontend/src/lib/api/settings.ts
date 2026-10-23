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
  /** Target in LUFS (-30 to -5); null means loudness matching is off. */
  loudness_target_lufs: number | null;
}

/** Queue the library-wide loudness re-gain job (admin only). */
export function regainLibrary(): Promise<{ job_id: string }> {
  return api<{ job_id: string }>("/api/admin/maintenance/regain", { method: "POST" });
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
