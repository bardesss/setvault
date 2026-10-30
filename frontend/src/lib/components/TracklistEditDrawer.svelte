<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { _ } from "svelte-i18n";
  import { deleteEntry, patchEntry, type TracklistEntry } from "#lib/api/tracklist.ts";
  import { upsertEntry, removeEntry } from "#lib/stores/tracklist.ts";

  export let slug: string;
  export let entry: TracklistEntry;

  let raw_label = entry.raw_label;
  let start_seconds = entry.start_seconds;
  let edit_notes = entry.edit_notes ?? "";
  let saving = false;
  const dispatch = createEventDispatcher();

  async function save() {
    saving = true;
    try {
      const updated = await patchEntry(slug, entry.id, {
        raw_label,
        start_seconds,
        edit_notes: edit_notes || null,
      });
      upsertEntry(updated);
      dispatch("close");
    } finally {
      saving = false;
    }
  }

  async function remove() {
    if (!confirm($_("tracklist.confirm_delete"))) return;
    await deleteEntry(slug, entry.id);
    removeEntry(entry.id);
    dispatch("close");
  }

  function handleKeydown(ev: KeyboardEvent) {
    if (ev.key === "Escape") dispatch("close");
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<div
  class="backdrop"
  on:click={() => dispatch("close")}
  role="presentation"
></div>
<div class="drawer" role="dialog" aria-label={$_("tracklist.edit_entry")}>
  <header>
    <h3>{$_("tracklist.edit_entry")}</h3>
    <button on:click={() => dispatch("close")} aria-label={$_("components.close_lower")}>✕</button>
  </header>
  <label>
    {$_("tracklist.field_label")}
    <input type="text" bind:value={raw_label} on:keydown={(e) => e.key === "Enter" && save()} />
  </label>
  <label>
    {$_("tracklist.field_start_seconds")}
    <input type="number" bind:value={start_seconds} min="0" />
  </label>
  <label>
    {$_("tracklist.field_notes")}
    <textarea bind:value={edit_notes} rows="3"></textarea>
  </label>
  <footer>
    <button class="danger" on:click={remove}>{$_("tracklist.delete")}</button>
    <button class="primary" on:click={save} disabled={saving}>{$_("tracklist.save")}</button>
  </footer>
</div>

<style>
  .backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: var(--z-overlay); }
  .drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(420px, 100vw);
            background: var(--bg-elevated); padding: var(--sp-6); z-index: var(--z-modal);
            box-shadow: var(--shadow-lg); display: grid; gap: var(--sp-3);
            align-content: start; }
  header { display: flex; justify-content: space-between; align-items: center; }
  label { display: grid; gap: var(--sp-1); }
  input, textarea { padding: var(--sp-2); border: 1px solid var(--border-default);
                    border-radius: var(--r-sm); background: var(--bg-input);
                    color: var(--text-default); font: inherit; }
  footer { display: flex; gap: var(--sp-2); justify-content: space-between; margin-top: var(--sp-2); }
  .danger { color: var(--accent-error); background: none; border: 1px solid var(--accent-error);
            padding: var(--sp-2) var(--sp-3); border-radius: var(--r-sm); cursor: pointer; }
  .primary { background: var(--accent); color: var(--text-on-accent); border: none;
             padding: var(--sp-2) var(--sp-3); border-radius: var(--r-sm); cursor: pointer; }
</style>
