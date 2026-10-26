<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import { createBookmark, deleteBookmark, listForSet, type Bookmark } from "#lib/api/bookmarks.ts";
  import { player, seekTo } from "#lib/stores/audio.ts";
  import { shouldIgnoreShortcut } from "#lib/keyboard.ts";
  import { fmtDuration } from "#lib/format.ts";

  export let slug: string;
  export let flat = false;

  let bookmarks: Bookmark[] = [];
  // The set-level toggle stays disabled until the initial list has loaded, so
  // its pressed state reflects the server before the user can flip it.
  let loaded = false;
  // Set once the user changes bookmarks locally (the B shortcut works before
  // the list arrives); the initial load then merges instead of overwriting.
  let touched = false;

  onMount(async () => {
    try {
      const fetched = await listForSet(slug);
      if (touched) {
        const known = new Set(fetched.map((b) => b.id));
        bookmarks = [...fetched, ...bookmarks.filter((b) => !known.has(b.id))];
      } else {
        bookmarks = fetched;
      }
    } catch {
      /* best-effort */
    } finally {
      loaded = true;
    }
  });

  $: setBookmark = bookmarks.find((b) => b.position_seconds === null) ?? null;

  async function toggleSetLevel() {
    if (setBookmark) {
      const id = setBookmark.id;
      await deleteBookmark(slug, id);
      bookmarks = bookmarks.filter((b) => b.id !== id);
    } else {
      const b = await createBookmark(slug, null, null);
      bookmarks = [...bookmarks, b];
    }
  }

  async function bookmarkPlayhead() {
    const t = Math.floor($player.position ?? 0);
    const b = await createBookmark(slug, t, null);
    touched = true;
    bookmarks = [...bookmarks, b];
  }

  async function removeTimestamped(id: string) {
    await deleteBookmark(slug, id);
    bookmarks = bookmarks.filter((b) => b.id !== id);
  }

  function onKey(ev: KeyboardEvent) {
    if (shouldIgnoreShortcut(ev, ev.key)) return;
    if (ev.key === "b" || ev.key === "B") {
      ev.preventDefault();
      void bookmarkPlayhead();
    }
  }
</script>

<svelte:window on:keydown={onKey} />

<button
  class="bookmark"
  class:flat
  on:click={toggleSetLevel}
  aria-pressed={!!setBookmark}
  disabled={!loaded}
>
  {setBookmark ? "★" : "☆"}
  {$_(setBookmark ? "bookmarks.unsave_set" : "bookmarks.save_set")}
</button>

<ul class="ts-bookmarks">
  {#each bookmarks.filter((b) => b.position_seconds !== null) as b (b.id)}
    {@const pos = b.position_seconds ?? 0}
    <li>
      <button class="seek" on:click={() => seekTo(pos)}>{fmtDuration(pos)}</button>
      <button class="remove" aria-label={$_("bookmarks.remove")} on:click={() => removeTimestamped(b.id)}>✕</button>
    </li>
  {/each}
</ul>

<style>
  .bookmark {
    padding: var(--sp-2) var(--sp-3);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    background: var(--bg-surface);
    cursor: pointer;
    color: var(--text-default);
    font: inherit;
  }
  .bookmark.flat { width: 100%; }
  .ts-bookmarks {
    list-style: none;
    padding: 0;
    margin: var(--sp-2) 0 0 0;
    display: flex;
    gap: var(--sp-2);
    flex-wrap: wrap;
  }
  .ts-bookmarks li {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
    padding: 2px var(--sp-2);
    border: 1px solid var(--border-default);
    border-radius: var(--r-pill);
    font-family: var(--font-mono);
    font-size: var(--ts-xs);
  }
  .ts-bookmarks button {
    background: none;
    border: none;
    cursor: pointer;
    color: inherit;
    font: inherit;
  }
  @media (max-width: 600px) {
    .bookmark {
      width: 100%;
      min-height: 44px;
      text-align: center;
    }
    .ts-bookmarks { gap: var(--sp-1); }
    .ts-bookmarks li { padding: var(--sp-1) var(--sp-2); min-height: 36px; }
  }
</style>
