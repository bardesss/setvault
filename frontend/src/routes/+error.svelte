<script lang="ts">
  import { _ } from "svelte-i18n";
  import { page } from "$app/state";
  import { setupI18n } from "#lib/i18n/index.ts";

  // The root layout (which normally initialises i18n) is not rendered when its
  // own load throws, so make sure the dictionary is ready here. Idempotent.
  setupI18n();
</script>

<section class="error-page">
  <h2>{$_("error.title")}</h2>
  <p class="admin-msg is-error" role="alert">
    <strong>{page.status}</strong>
    {page.error?.message ?? ""}
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
