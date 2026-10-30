<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { _ } from "svelte-i18n";
  import { listTracklist, timeShift } from "#lib/api/tracklist.ts";
  import { setEntries, tracklist } from "#lib/stores/tracklist.ts";

  export let slug: string;

  let after_seconds = 0;
  let delta_seconds = 0;
  let busy = false;
  const dispatch = createEventDispatcher();

  $: affected = $tracklist.entries.filter((e) => e.start_seconds > after_seconds).length;

  async function apply() {
    busy = true;
    try {
      await timeShift(slug, after_seconds, delta_seconds);
      const refreshed = await listTracklist(slug);
      setEntries(refreshed);
      dispatch("close");
    } finally {
      busy = false;
    }
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
<div class="dialog" role="dialog" aria-label={$_("tracklist.time_shift")}>
  <h3>{$_("tracklist.time_shift")}</h3>
  <label>
    {$_("tracklist.shift_after")}
    <input type="number" bind:value={after_seconds} min="0" />
  </label>
  <label>
    {$_("tracklist.shift_delta")}
    <input type="number" bind:value={delta_seconds} />
  </label>
  <p class="preview">{$_("tracklist.shift_preview", { values: { count: affected } })}</p>
  <footer>
    <button on:click={() => dispatch("close")}>{$_("tracklist.cancel")}</button>
    <button class="primary" on:click={apply} disabled={busy || affected === 0}>
      {$_("tracklist.apply")}
    </button>
  </footer>
</div>

<style>
  .backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: var(--z-overlay); }
  .dialog { position: fixed; top: 20vh; left: 50%; transform: translateX(-50%);
            width: min(420px, 92vw); background: var(--bg-elevated); padding: var(--sp-6);
            box-shadow: var(--shadow-lg);
            border-radius: var(--r-md); z-index: var(--z-modal); display: grid; gap: var(--sp-3); }
  label { display: grid; gap: var(--sp-1); }
  input { padding: var(--sp-2); border: 1px solid var(--border-default); border-radius: var(--r-sm);
          background: var(--bg-input); color: var(--text-default); font: inherit; }
  .preview { color: var(--text-muted); font-style: italic; }
  footer { display: flex; justify-content: space-between; gap: var(--sp-2); }
  .primary { background: var(--accent); color: var(--text-on-accent); border: none;
             padding: var(--sp-2) var(--sp-3); border-radius: var(--r-sm); cursor: pointer; }
</style>
