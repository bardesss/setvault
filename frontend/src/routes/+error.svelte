<script lang="ts">
  import { _ } from "svelte-i18n";
  import { page } from "$app/state";
  import { setupI18n } from "#lib/i18n/index.ts";

  // The root layout (which normally initialises i18n) is not rendered when its
  // own load throws, so make sure the dictionary is ready here. Idempotent.
  setupI18n();

  // Messages our own route loads throw (in English, before i18n may be ready);
  // shown translated. Anything else (server detail) is shown as-is.
  const LOAD_ERRORS: Record<string, string> = {
    "Not Found": "error.page_not_found",
    "not found": "error.not_found",
    "Artist not found": "error.artist_not_found",
    "Party not found": "error.party_not_found",
    "Series not found": "error.series_not_found",
    "Venue not found": "error.venue_not_found",
    "Set not found": "error.set_not_found",
    "Failed to load library": "error.library_load_failed",
    "Failed to load set": "error.set_load_failed",
  };
</script>

<section class="error-page">
  <h2>{$_("error.title")}</h2>
  <p class="admin-msg is-error" role="alert">
    <strong>{page.status}</strong>
    {LOAD_ERRORS[page.error?.message ?? ""] ? $_(LOAD_ERRORS[page.error?.message ?? ""]) : (page.error?.message ?? "")}
  </p>
  <p><a href="/">{$_("error.back_home")}</a></p>
</section>

<style>
  .error-page {
    padding: var(--sp-6);
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .error-page h2 { margin: 0; }
</style>
