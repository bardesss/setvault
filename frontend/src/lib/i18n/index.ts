import { addMessages, getLocaleFromNavigator, init, register } from "svelte-i18n";
import en from "./locales/en.json";
import { applyLocale, pickStartLocale, readCachedLocale } from "./locale.ts";

let ready: Promise<void> | null = null;

/** Registers the languages and loads the start-up one. English is bundled;
 *  the others are fetched on first use. Resolves once messages are ready. */
export function setupI18n(): Promise<void> {
  if (ready) return ready;
  addMessages("en", en);
  register("nl", () => import("./locales/nl.json"));
  const start = pickStartLocale({
    cached: readCachedLocale(),
    navigator: typeof window !== "undefined" ? getLocaleFromNavigator() : null,
  });
  init({ fallbackLocale: "en", initialLocale: "en" });
  ready = applyLocale(start).then(() => {
    if (typeof window !== "undefined") (window as any).__i18n_initialized__ = true;
  });
  return ready;
}
