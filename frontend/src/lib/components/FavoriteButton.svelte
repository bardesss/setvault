<script lang="ts">
  import { _ } from "svelte-i18n";
  import { favorite, unfavorite } from "#lib/api/favorites.ts";

  export let slug: string;
  export let initial = false;

  let pressed = initial;
  let busy = false;
  let failed = false;

  async function toggle() {
    if (busy) return;
    const next = !pressed;
    busy = true;
    failed = false;
    pressed = next; // optimistic
    try {
      if (next) await favorite(slug);
      else await unfavorite(slug);
    } catch {
      pressed = !next; // revert
      failed = true;
    } finally {
      busy = false;
    }
  }
</script>

<button
  type="button"
  class="favorite"
  on:click={toggle}
  aria-pressed={pressed}
  disabled={busy}
>
  <span aria-hidden="true">{pressed ? "♥" : "♡"}</span>
  {$_(pressed ? "favorites.remove" : "favorites.add")}
</button>
{#if failed}<span class="fav-error" role="alert">{$_("favorites.error")}</span>{/if}

<style>
  .favorite {
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    background: var(--bg-surface);
    cursor: pointer;
    color: var(--text-default);
    font: inherit;
  }
  .favorite[aria-pressed="true"] { color: var(--accent); border-color: var(--accent); }
  .favorite:disabled { opacity: 0.6; cursor: default; }
  .fav-error { color: var(--text-muted); font-size: var(--ts-sm); margin-left: var(--sp-2); }
</style>
