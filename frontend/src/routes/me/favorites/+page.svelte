<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import SetCard from "#lib/components/SetCard.svelte";
  import { listMyFavorites, type FavoriteItem } from "#lib/api/favorites.ts";

  const LIMIT = 50;
  let items: FavoriteItem[] = [];
  let total = 0;
  let loaded = false;
  let loading = false;
  let failed = false;

  async function loadMore() {
    loading = true;
    failed = false;
    try {
      const r = await listMyFavorites({ limit: LIMIT, offset: items.length });
      const seen = new Set(items.map((s) => s.id));
      items = [...items, ...r.items.filter((s) => !seen.has(s.id))];
      total = r.total;
    } catch {
      failed = true;
    } finally {
      loading = false;
      loaded = true;
    }
  }

  onMount(loadMore);
</script>

<svelte:head><title>{$_("favorites.my_title")} — SetVault</title></svelte:head>

<section class="favorites-body">
  <h1 class="favorites-heading">{$_("favorites.my_title")}</h1>

  {#if !loaded}
    <p class="hint">Loading…</p>
  {:else if items.length === 0 && failed}
    <p class="hint">{$_("favorites.load_error")}</p>
  {:else if items.length === 0}
    <p class="hint">{$_("favorites.empty")}</p>
  {:else}
    <div class="grid">
      {#each items as s (s.slug)}
        <SetCard set={s} />
      {/each}
    </div>
    {#if failed}<p class="hint">{$_("favorites.load_error")}</p>{/if}
    {#if items.length < total}
      <button type="button" class="load-more" disabled={loading} on:click={loadMore}>
        {$_("favorites.load_more")}
      </button>
    {/if}
  {/if}
</section>

<style>
  .favorites-body {
    padding: var(--sp-4) var(--sp-6) var(--sp-8);
    display: grid;
    gap: var(--sp-4);
  }
  .favorites-heading {
    font-size: var(--ts-2xl);
    letter-spacing: var(--ls-tight);
    color: var(--text-strong);
    margin: 0;
  }
  .hint {
    padding: var(--sp-8);
    text-align: center;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: var(--ts-md);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: var(--sp-3);
  }
  .load-more {
    justify-self: center;
    padding: var(--sp-2) var(--sp-4);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    color: inherit;
    cursor: pointer;
  }
</style>
