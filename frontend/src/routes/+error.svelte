<script lang="ts">
  import { _ } from "svelte-i18n";
  import { page } from "$app/state";
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
