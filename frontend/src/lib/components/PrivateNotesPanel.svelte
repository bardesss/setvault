<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import { getNote, saveNote, type PrivateNote } from "#lib/api/notes.ts";

  export let slug: string;
  export let flat = false;

  let collapsed = flat ? false : true;
  let note: PrivateNote = { body_md: "", body_html: "", updated_at: null };
  let dirty = false;
  let saveTimer: ReturnType<typeof setTimeout> | null = null;
  let editing = false;

  onMount(async () => {
    try {
      note = await getNote(slug);
    } catch {
      /* best-effort */
    }
  });

  function onInput(e: Event) {
    note.body_md = (e.target as HTMLTextAreaElement).value;
    dirty = true;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      try {
        const out = await saveNote(slug, note.body_md);
        note = out;
        dirty = false;
      } catch {
        /* keep dirty=true so user sees it didn't save */
      }
    }, 1000);
  }
</script>

<section class="notes" class:flat data-open={!collapsed}>
  <header>
    {#if flat}
      <span class="notes-label">{$_("notes.heading")}</span>
    {:else}
      <button on:click={() => (collapsed = !collapsed)} aria-expanded={!collapsed}>
        {collapsed ? "▶" : "▼"} {$_("notes.heading")}
      </button>
    {/if}
    {#if dirty}<span class="status">{$_("notes.saving")}</span>{/if}
  </header>
  {#if !collapsed}
    <div class="body">
      {#if editing}
        <textarea
          bind:value={note.body_md}
          on:input={onInput}
          rows="8"
          placeholder={$_("notes.placeholder")}
          aria-label={$_("notes.heading")}
        ></textarea>
        <button class="done" on:click={() => (editing = false)}>{$_("notes.done")}</button>
      {:else}
        <button class="preview-toggle" on:click={() => (editing = true)}>{$_("notes.edit")}</button>
        {#if note.body_md}
          {@html note.body_html}
        {:else}
          <p class="empty">{$_("notes.empty")}</p>
        {/if}
      {/if}
    </div>
  {/if}
</section>

<style>
  .notes {
    padding: var(--sp-4);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
  }
  .notes.flat { padding: 0; border: none; }
  .notes-label { color: var(--text-default); font: inherit; }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  header button {
    background: none;
    border: none;
    color: var(--text-default);
    cursor: pointer;
    font: inherit;
    text-align: left;
  }
  .body {
    margin-top: var(--sp-3);
    display: grid;
    gap: var(--sp-2);
  }
  textarea {
    width: 100%;
    box-sizing: border-box;
    padding: var(--sp-2);
    font: inherit;
    background: var(--bg-input);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    color: var(--text-default);
    resize: vertical;
  }
  .done,
  .preview-toggle {
    justify-self: start;
    padding: var(--sp-1) var(--sp-3);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    background: var(--bg-surface);
    color: var(--text-default);
    cursor: pointer;
    font: inherit;
  }
  .status {
    color: var(--text-muted);
    font-size: var(--ts-sm);
  }
  .empty {
    color: var(--text-faint);
    font-style: italic;
  }

  @media (max-width: 600px) {
    /* Header stays inline so the user has somewhere to tap. When opened,
       the body slides up as a fixed bottom-sheet above the NavRail. */
    .notes[data-open="true"] .body {
      position: fixed;
      left: 0;
      right: 0;
      bottom: calc(64px + env(safe-area-inset-bottom, 0px));
      max-height: 70vh;
      overflow-y: auto;
      padding: var(--sp-3);
      background: var(--bg-surface);
      border-top: 1px solid var(--border-default);
      border-radius: var(--r-md) var(--r-md) 0 0;
      box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.2);
      z-index: 80;
      margin-top: 0;
    }
    textarea { font-size: 16px; }  /* prevent iOS auto-zoom on focus */
  }
</style>
