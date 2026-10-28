import { api } from "./client";
import type { SupportedLocale } from "#lib/i18n/locale.ts";

/** Saves the UI language on the account; null goes back to following the browser. */
export const setMyLocale = (locale: SupportedLocale | null) =>
  api<void>("/api/me", { method: "PATCH", body: JSON.stringify({ locale }) });
