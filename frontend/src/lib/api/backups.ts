import { api } from "./client";

export interface BackupFile {
  name: string;
  bytes: number;
  created_at: string;
}

export interface BackupLast {
  at: string | null;
  status: string | null;
  error: string | null;
  bytes: number | null;
}

export interface BackupList {
  dir: string;
  dir_persistent: boolean;
  tz: string;
  files: BackupFile[];
  last: BackupLast;
}

export function listBackups(): Promise<BackupList> {
  return api<BackupList>("/api/admin/backups");
}

/** Queue one backup now (admin only). */
export function runBackup(): Promise<{ job_id: string }> {
  return api<{ job_id: string }>("/api/admin/backups/run", { method: "POST" });
}

export function deleteBackup(name: string): Promise<void> {
  return api<void>(`/api/admin/backups/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export function backupUrl(name: string): string {
  return `/api/admin/backups/${encodeURIComponent(name)}`;
}
