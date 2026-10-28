import { get } from "svelte/store";
import { getLocaleFromNavigator, locale, waitLocale } from "svelte-i18n";

/** UI languages, in picker order. The backend keeps the same list in
 *  `packages/core/src/setvault_core/locales.py`; a test checks they match. */
export const SUPPORTED_LOCALES = ["en", "nl", "de", "es", "fr"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

/** Each language in its own name, for the picker. */
export const LOCALE_NAMES: Record<SupportedLocale, string> = {
  en: "English",
  nl: "Nederlands",
  de: "Deutsch",
  es: "Español",
  fr: "Français",
};

const CACHE_KEY = "setvault.locale";

/** "nl-NL" → "nl"; anything unsupported (or empty) → null. */
export function normalizeLocale(v: string | null | undefined): SupportedLocale | null {
  if (!v) return null;
  const primary = v.trim().toLowerCase().split(/[-_]/)[0];
  return (SUPPORTED_LOCALES as readonly string[]).includes(primary)
    ? (primary as SupportedLocale)
    : null;
}

/** Start-up choice: the cached choice, else the browser language, else English. */
export function pickStartLocale(opts: {
  cached: string | null;
  navigator: string | null;
}): SupportedLocale {
  return normalizeLocale(opts.cached) ?? normalizeLocale(opts.navigator) ?? "en";
}

export function readCachedLocale(): string | null {
  try {
    return localStorage.getItem(CACHE_KEY);
  } catch {
    return null;
  }
}

/** Remembers the choice on this device; null forgets it ("follow the browser"). */
export function writeCachedLocale(l: SupportedLocale | null): void {
  try {
    if (l) localStorage.setItem(CACHE_KEY, l);
    else localStorage.removeItem(CACHE_KEY);
  } catch {
    // private mode or blocked storage: the account setting still applies
  }
}

/** Switches the UI language and waits until its messages are loaded. A file
 *  that fails to load (offline, missing chunk) falls back to English, so the
 *  caller's render gate always opens. */
export async function applyLocale(l: SupportedLocale): Promise<void> {
  try {
    await locale.set(l);
    await waitLocale(l);
  } catch {
    if (l === "en") return;
    l = "en";
    await locale.set(l);
  }
  if (typeof document !== "undefined") document.documentElement.lang = l;
}

/** The browser's language if supported, else English: what "follow the
 *  browser" means. */
export function browserLocale(): SupportedLocale {
  const nav = typeof navigator !== "undefined" ? getLocaleFromNavigator() : null;
  return normalizeLocale(nav) ?? "en";
}

/** Applies the language saved on the account (null: follow the browser) and
 *  remembers it on this device for the next start. An unsupported saved value
 *  counts as null. */
export async function followAccountLocale(saved: string | null | undefined): Promise<void> {
  const chosen = normalizeLocale(saved);
  writeCachedLocale(chosen);
  const target = chosen ?? browserLocale();
  if (get(locale) !== target) await applyLocale(target);
}
