<script lang="ts">
  import { tick } from "svelte";
  import { _ } from "svelte-i18n";
  import {
    addPlaylistItem,
    createPlaylist,
    listSetPlaylists,
    removePlaylistItem,
    type SetPlaylist,
  } from "#lib/api/playlists.ts";
  import { ApiError } from "#lib/api/client.ts";
  import { toast } from "#lib/stores/toast.ts";

  export let slug: string;
  export let compact = false;

  let root: HTMLElement;
  let trigger: HTMLButtonElement;
  let nameInput: HTMLInputElement | undefined;
  let open = false;
  let loading = false;
  let unavailable = false; // draft/deleted sets 404 here; stay quiet about it.
  let failed = false;
  let playlists: SetPlaylist[] = [];
  let creating = false;
  let newName = "";
  let busy = false;

  async function openMenu() {
    open = true;
    creating = false;
    newName = "";
    loading = true;
    unavailable = false;
    failed = false;
    try {
      playlists = (await listSetPlaylists(slug)).items;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) unavailable = true;
      else failed = true;
    } finally {
      loading = false;
    }
  }

  function close(refocus = false) {
    open = false;
    if (refocus) trigger?.focus();
  }

  function onTrigger() {
    if (open) close();
    else void openMenu();
  }

  async function toggleItem(p: SetPlaylist) {
    if (busy) return;
    busy = true;
    const next = !p.contains;
    playlists = playlists.map((x) => (x.id === p.id ? { ...x, contains: next } : x));
    try {
      if (next) await addPlaylistItem(p.id, slug);
      else await removePlaylistItem(p.id, slug);
    } catch {
      playlists = playlists.map((x) => (x.id === p.id ? { ...x, contains: !next } : x));
      toast.error($_("playlists.action_error"));
    } finally {
      busy = false;
    }
  }

  async function startCreate() {
    creating = true;
    await tick();
    nameInput?.focus();
  }

  async function submitCreate() {
    const name = newName.trim();
    if (!name || busy) return;
    busy = true;
    try {
      const created = await createPlaylist(name);
      try {
        await addPlaylistItem(created.id, slug);
        playlists = [...playlists, { id: created.id, name: created.name, contains: true }];
      } catch {
        playlists = [...playlists, { id: created.id, name: created.name, contains: false }];
        toast.error($_("playlists.action_error"));
      }
      creating = false;
      newName = "";
    } catch {
      toast.error($_("playlists.action_error"));
    } finally {
      busy = false;
    }
  }

  function onWindowClick(e: MouseEvent) {
    if (open && root && !root.contains(e.target as Node)) close();
  }

  function onKeydown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(true);
    } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !creating) {
      const items = Array.from(root.querySelectorAll<HTMLElement>('[role^="menuitem"]'));
      if (items.length === 0) return;
      e.preventDefault();
      const i = items.indexOf(document.activeElement as HTMLElement);
      const step = e.key === "ArrowDown" ? 1 : -1;
      items[(i + step + items.length) % items.length].focus();
    }
  }
</script>

<svelte:window on:click={onWindowClick} />

<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="add-to-playlist" class:compact bind:this={root} on:keydown={onKeydown}>
  <button
    type="button"
    class="btn atp-trigger"
    bind:this={trigger}
    aria-haspopup="menu"
    aria-expanded={open}
    aria-label={$_("playlists.add_to")}
    on:click={onTrigger}
  >
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
      <path d="M2 4h9M2 8h9M2 12h5M12 9v5M9.5 11.5h5" />
    </svg>
    {#if !compact}<span>{$_("playlists.add_to")}</span>{/if}
  </button>

  {#if open}
    <div class="atp-menu" role="menu" aria-label={$_("playlists.add_to")}>
      {#if loading}
        <div class="atp-note">…</div>
      {:else if unavailable}
        <div class="atp-note">{$_("playlists.none_available")}</div>
      {:else if failed}
        <div class="atp-note">{$_("playlists.load_error")}</div>
      {:else}
        {#each playlists as p (p.id)}
          <button
            type="button"
            class="atp-item"
            role="menuitemcheckbox"
            aria-checked={p.contains}
            on:click={() => toggleItem(p)}
          >
            <span class="atp-check" aria-hidden="true">{p.contains ? "✓" : ""}</span>
            <span class="atp-name">{p.name}</span>
          </button>
        {/each}
        {#if creating}
          <form class="atp-create" on:submit|preventDefault={submitCreate}>
            <input
              bind:this={nameInput}
              bind:value={newName}
              maxlength="200"
              placeholder={$_("playlists.create_placeholder")}
              aria-label={$_("playlists.create_placeholder")}
            />
          </form>
        {:else}
          <button type="button" class="atp-item" role="menuitem" on:click={startCreate}>
            <span class="atp-check" aria-hidden="true"></span>
            <span class="atp-name">{$_("playlists.new_playlist")}</span>
          </button>
        {/if}
      {/if}
    </div>
  {/if}
</div>

<style>
  .add-to-playlist { position: relative; display: inline-block; }
  .atp-trigger { display: inline-flex; align-items: center; gap: var(--sp-2); }
  .compact .atp-trigger { padding: 4px 6px; }
  .atp-menu {
    position: absolute;
    right: 0;
    top: calc(100% + 4px);
    z-index: 30;
    min-width: 220px;
    max-width: 280px;
    max-height: 320px;
    overflow-y: auto;
    padding: var(--sp-1);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    box-shadow: 0 6px 24px rgb(0 0 0 / 0.3);
    display: grid;
    gap: 2px;
  }
  .atp-item {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-2);
    background: transparent;
    border: 0;
    border-radius: var(--r-sm);
    color: var(--text-default);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .atp-item:hover, .atp-item:focus-visible { background: var(--bg-hover, rgb(255 255 255 / 0.08)); }
  .atp-check { width: 1em; color: var(--accent); }
  .atp-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .atp-note { padding: var(--sp-2); color: var(--text-muted); font-size: var(--ts-sm); }
  .atp-create { padding: var(--sp-1); }
  .atp-create input { width: 100%; box-sizing: border-box; }
</style>
