<script lang="ts">
  import { onMount, tick } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { toStore } from "svelte/store";
  import { _ } from "svelte-i18n";
  import SetRow from "#lib/components/SetRow.svelte";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import { ApiError } from "#lib/api/client.ts";
  import {
    deletePlaylist,
    getPlaylist,
    removePlaylistItem,
    renamePlaylist,
    reorderPlaylist,
    type PlaylistDetail,
  } from "#lib/api/playlists.ts";
  import { formatTime, playQueue } from "#lib/stores/audio.ts";
  import { toast } from "#lib/stores/toast.ts";

  // Legacy `$:` statements don't track rune state like `page`; a store does.
  const idStore = toStore(() => page.params.id ?? "");
  $: id = $idStore;

  let playlist: PlaylistDetail | null = null;
  let loaded = false;
  let notFound = false;
  let failed = false;
  let editing = false;
  let draftName = "";
  let renameInput: HTMLInputElement | undefined;
  let confirmDelete = false;
  let canDrag = false;
  let dragFrom: number | null = null;
  let dragOver: number | null = null;

  async function load() {
    try {
      playlist = await getPlaylist(id);
      notFound = false;
      failed = false;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) notFound = true;
      else failed = true;
    } finally {
      loaded = true;
    }
  }

  onMount(() => {
    canDrag = window.matchMedia("(pointer: fine)").matches;
    void load();
  });

  $: items = playlist?.items ?? [];

  let reordering = false;

  async function reorder(slugs: string[]) {
    if (!playlist || reordering) return;
    reordering = true;
    try {
      playlist = await reorderPlaylist(id, slugs);
    } catch (e) {
      if (e instanceof ApiError && e.status === 400) {
        toast.error($_("playlists.reorder_conflict"));
        await load();
      } else {
        toast.error($_("playlists.action_error"));
      }
    } finally {
      reordering = false;
    }
  }

  function move(from: number, to: number) {
    if (reordering || to < 0 || to >= items.length || from === to) return;
    const slugs = items.map((i) => i.slug);
    const [slug] = slugs.splice(from, 1);
    slugs.splice(to, 0, slug);
    void reorder(slugs);
  }

  async function remove(slug: string) {
    try {
      await removePlaylistItem(id, slug);
      await load();
    } catch {
      toast.error($_("playlists.action_error"));
    }
  }

  async function startRename() {
    if (!playlist) return;
    draftName = playlist.name;
    editing = true;
    await tick();
    renameInput?.select();
  }

  async function saveRename() {
    const name = draftName.trim();
    if (!playlist || !name) return;
    if (name === playlist.name) {
      editing = false;
      return;
    }
    try {
      const updated = await renamePlaylist(id, name);
      playlist = { ...playlist, name: updated.name, updated_at: updated.updated_at };
      editing = false;
    } catch {
      toast.error($_("playlists.action_error"));
    }
  }

  async function doDelete() {
    confirmDelete = false;
    try {
      await deletePlaylist(id);
      await goto("/playlists");
    } catch {
      toast.error($_("playlists.action_error"));
    }
  }

  function playAll() {
    void playQueue(items.map((i) => i.slug), 0);
  }

  function onDrop(to: number) {
    const from = dragFrom;
    dragFrom = dragOver = null;
    if (from != null) move(from, to);
  }
</script>

<svelte:head><title>{playlist?.name ?? $_("playlists.title")} — SetVault</title></svelte:head>

<section class="playlist-body">
  <nav class="crumb"><a href="/playlists">{$_("playlists.title")}</a></nav>

  {#if !loaded}
    <p class="hint">…</p>
  {:else if notFound}
    <p class="hint">{$_("playlists.not_found")}</p>
  {:else if failed || !playlist}
    <p class="hint">{$_("playlists.load_error")}</p>
  {:else}
    <header class="head">
      {#if editing}
        <form class="rename" on:submit|preventDefault={saveRename}>
          <input
            bind:this={renameInput}
            bind:value={draftName}
            maxlength="200"
            aria-label={$_("playlists.rename")}
            on:keydown={(e) => e.key === "Escape" && (editing = false)}
          />
        </form>
      {:else}
        <h1 class="title">{playlist.name}</h1>
      {/if}
      <div class="sub">
        {$_("playlists.items", { values: { count: playlist.item_count } })}
        · {formatTime(playlist.total_duration_seconds)}
      </div>
      <div class="actions">
        <button
          type="button"
          class="btn btn-primary"
          data-test="playlist-play-all"
          disabled={items.length === 0}
          on:click={playAll}
        >{$_("playlists.play_all")}</button>
        {#if !editing}
          <button type="button" class="btn" on:click={startRename}>{$_("playlists.rename")}</button>
        {/if}
        <button type="button" class="btn btn-danger" on:click={() => (confirmDelete = true)}>
          {$_("playlists.delete")}
        </button>
      </div>
    </header>

    {#if items.length === 0}
      <p class="hint">{$_("playlists.no_items")}</p>
    {:else}
      <ul class="rows">
        {#each items as item, i (item.slug)}
          <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
          <li
            class="item"
            class:drag-over={dragOver === i && dragFrom !== i}
            draggable={canDrag && !reordering}
            on:dragstart={(e) => {
              dragFrom = i;
              if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
            }}
            on:dragover={(e) => {
              if (dragFrom == null) return;
              e.preventDefault();
              dragOver = i;
            }}
            on:drop|preventDefault={() => onDrop(i)}
            on:dragend={() => (dragFrom = dragOver = null)}
          >
            <div class="row-main">
              <SetRow
                slug={item.slug}
                title={item.title}
                artist={item.artists.map((a) => a.name).join(", ")}
                venue={item.venue?.name ?? ""}
                durationSeconds={item.duration_seconds}
                date={item.date}
              />
            </div>
            <div class="row-actions">
              <button
                type="button"
                class="btn btn-icon"
                disabled={i === 0 || reordering}
                aria-label={$_("playlists.move_up", { values: { title: item.title } })}
                on:click={() => move(i, i - 1)}
              >↑</button>
              <button
                type="button"
                class="btn btn-icon"
                disabled={i === items.length - 1 || reordering}
                aria-label={$_("playlists.move_down", { values: { title: item.title } })}
                on:click={() => move(i, i + 1)}
              >↓</button>
              <button
                type="button"
                class="btn btn-icon"
                aria-label={$_("playlists.remove", { values: { title: item.title } })}
                on:click={() => remove(item.slug)}
              >✕</button>
            </div>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<ConfirmDialog
  open={confirmDelete}
  title={$_("playlists.delete_confirm_title")}
  message={$_("playlists.delete_confirm_message", { values: { name: playlist?.name ?? "" } })}
  confirmLabel={$_("playlists.delete")}
  danger
  on:confirm={doDelete}
  on:cancel={() => (confirmDelete = false)}
/>

<style>
  .playlist-body {
    padding: var(--sp-4) var(--sp-6) var(--sp-8);
    display: grid;
    gap: var(--sp-4);
    grid-template-columns: minmax(0, 1fr);
  }
  .crumb a { color: var(--text-muted); text-decoration: none; font-size: var(--ts-sm); }
  .title {
    margin: 0;
    font-size: var(--ts-2xl);
    letter-spacing: var(--ls-tight);
    color: var(--text-strong);
  }
  .rename input { font-size: var(--ts-xl); width: 100%; max-width: 520px; box-sizing: border-box; }
  .head { display: grid; gap: var(--sp-2); }
  .sub { color: var(--text-faint); font-family: var(--font-mono); font-size: var(--ts-sm); }
  .actions { display: flex; flex-wrap: wrap; gap: var(--sp-2); }
  .hint {
    padding: var(--sp-8);
    text-align: center;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: var(--ts-md);
  }
  .rows { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--sp-1); }
  .item {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    border-radius: var(--r-md);
    border: 1px solid transparent;
  }
  .item[draggable="true"] { cursor: grab; }
  .item.drag-over { border-color: var(--accent); }
  .row-main { flex: 1; min-width: 0; }
  .row-actions { display: flex; gap: var(--sp-1); flex-shrink: 0; }
</style>
