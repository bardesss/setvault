import { clearScopedCaches } from "../stores/offline";
import { api } from "./client";

export interface CurrentUser {
  id: string;
  email: string;
  username: string;
  display_name: string;
  role: "admin" | "user";
  /** Saved UI language; null follows the browser. */
  locale: string | null;
}

export function login(email: string, password: string) {
  return api<{ user: CurrentUser }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function logout() {
  try {
    await api<void>("/api/auth/logout", { method: "POST" });
  } finally {
    // Purge cached user-scoped data so it can't bleed to the next session.
    await clearScopedCaches();
    try { localStorage.removeItem("setvault.playQueue"); } catch { /* unavailable */ }
  }
}

export function me() {
  return api<CurrentUser>("/api/auth/me");
}

export function setupFirstAdmin(
  email: string,
  password: string,
  display_name?: string,
) {
  return api<CurrentUser>("/api/setup", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name }),
  });
}
