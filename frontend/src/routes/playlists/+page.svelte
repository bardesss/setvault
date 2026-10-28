<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import { createPlaylist, listPlaylists, type Playlist } from "#lib/api/playlists.ts";
  import { formatTime } from "#lib/stores/audio.ts";
  import { toast } from "#lib/stores/toast.ts";

  let items: Playlist[] = [];
  let loaded = false;
  let failed = false;
  let name = "";
  let creating = false;

  async function load() {
    try {
      items = (await listPlaylists()).items;
    } catch {
      failed = true;
    } finally {
      loaded = true;
    }
  }

  async function create() {
    const trimmed = name.trim();
    if (!trimmed || creating) return;
    creating = true;
    try {
      const created = await createPlaylist(trimmed);
      const { items: _items, ...summary } = created;
      items = [summary, ...items];
      name = "";
    } catch {
      toast.error($_("playlists.action_error"));
    } finally {
      creating = false;
    }
  }

  onMount(load);
</script>

<svelte:head><title>{$_("playlists.title")} — SetVault</title></svelte:head>

<section class="playlists-body">
  <h1 class="playlists-heading">{$_("playlists.title")}</h1>

  <form class="create" on:submit|preventDefault={create}>
    <input
      bind:value={name}
      maxlength="200"
      placeholder={$_("playlists.create_placeholder")}
      aria-label={$_("playlists.create_placeholder")}
    />
    <button type="submit" class="btn btn-primary" data-test="playlist-create" disabled={creating || !name.trim()}>
      {$_("playlists.create")}
    </button>
  </form>

  {#if !loaded}
    <p class="hint">…</p>
  {:else if failed}
    <p class="hint">{$_("playlists.load_error")}</p>
  {:else if items.length === 0}
    <p class="hint">{$_("playlists.empty")}</p>
  {:else}
    <ul class="list">
      {#each items as p (p.id)}
        <li>
          <a class="playlist-row" href={`/playlists/${p.id}`}>
            <span class="pl-name">{p.name}</span>
            <span class="pl-meta">
              {$_("playlists.items", { values: { count: p.item_count } })}
              · {formatTime(p.total_duration_seconds)}
            </span>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .playlists-body {
    padding: var(--sp-4) var(--sp-6) var(--sp-8);
    display: grid;
    gap: var(--sp-4);
    grid-template-columns: minmax(0, 1fr);
  }
  .playlists-heading {
    font-size: var(--ts-2xl);
    letter-spacing: var(--ls-tight);
    color: var(--text-strong);
    margin: 0;
  }
  .create { display: flex; gap: var(--sp-2); max-width: 520px; }
  .create input { flex: 1; min-width: 0; }
  .hint {
    padding: var(--sp-8);
    text-align: center;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: var(--ts-md);
  }
  .list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--sp-2); }
  .playlist-row {
    display: flex;
    justify-content: space-between;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    text-decoration: none;
    color: inherit;
  }
  .pl-name { font-weight: 700; }
  .pl-meta { color: var(--text-faint); font-size: var(--ts-sm); font-family: var(--font-mono); }
</style>
