<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import { bulkResolve } from "#lib/api/enrichment.ts";
  import { createEntry, listTracklist, type TracklistEntry } from "#lib/api/tracklist.ts";
  import { player, seekInSet } from "#lib/stores/audio.ts";
  import { shouldIgnoreShortcut } from "#lib/keyboard.ts";
  import { tracklist, setEntries, upsertEntry, removeEntry } from "#lib/stores/tracklist.ts";
  import ResolveCandidatesPopover from "./ResolveCandidatesPopover.svelte";
  import TracklistEditDrawer from "./TracklistEditDrawer.svelte";
  import TracklistImportModal from "./TracklistImportModal.svelte";
  import TimeShiftDialog from "./TimeShiftDialog.svelte";
  import { fmtDuration } from "#lib/format.ts";

  export let slug: string;

  let drawerEntry: TracklistEntry | null = null;
  let importModalOpen = false;
  let shiftOpen = false;
  let popoverEntry: TracklistEntry | null = null;
  let bulkBusy = false;
  let bulkStatus: string | null = null;

  onMount(async () => {
    try {
      const entries = await listTracklist(slug);
      setEntries(entries);
    } catch (e) {
      console.error("load tracklist failed", e);
    }
  });

  // At-playhead actions only make sense when this page's set is the loaded one.
  $: onThisSet = $player.set?.slug === slug;

  async function addAtPlayhead() {
    if (!onThisSet) return;
    const seconds = Math.floor($player.position);
    const tentative: TracklistEntry = {
      id: `pending-${Date.now()}`,
      position: $tracklist.entries.length,
      start_seconds: seconds,
      end_seconds: null,
      raw_label: $_("tracklist.new_entry"),
      edit_notes: null,
      status: "raw",
      confidence: null,
      track_id: null,
      mashup_with: [],
    };
    upsertEntry(tentative);
    try {
      const created = await createEntry(slug, {
        start_seconds: seconds,
        raw_label: $_("tracklist.new_entry"),
      });
      removeEntry(tentative.id);
      upsertEntry(created);
      drawerEntry = created;
    } catch (e) {
      removeEntry(tentative.id);
      console.error("add failed", e);
    }
  }

  function indexAt(entries: TracklistEntry[], pos: number | null): number {
    if (pos === null) return -1;
    return entries.findIndex((e, i) => {
      const next = entries[i + 1];
      return e.start_seconds <= pos && (!next || next.start_seconds > pos);
    });
  }

  function handleKeydown(ev: KeyboardEvent) {
    if (shouldIgnoreShortcut(ev, ev.key)) return;
    if (ev.key === "m" || ev.key === "M") {
      ev.preventDefault();
      addAtPlayhead();
    }
  }

  async function runBulkResolve() {
    bulkBusy = true;
    bulkStatus = null;
    try {
      const results = await bulkResolve(slug);
      const withCands = results.filter((r) => r.candidates.length > 0).length;
      bulkStatus = $_("tracklist.bulk_resolve_done", {
        values: { found: withCands, total: results.length },
      });
    } catch (e) {
      bulkStatus = e instanceof Error ? e.message : "error";
    } finally {
      bulkBusy = false;
    }
  }

  $: currentIdx = indexAt($tracklist.entries, onThisSet ? $player.position : null);
</script>

<svelte:window on:keydown={handleKeydown} />

<section class="tracks-section" aria-label={$_("tracklist.heading")}>
  <div class="tracks-header">
    <h3>{$_("tracklist.heading")} <b>· {$tracklist.entries.length} entries</b></h3>
    <div class="right">
      <button class="btn btn-sm" on:click={addAtPlayhead} disabled={!onThisSet} title={$_("tracklist.add_at_playhead")}>+ <span class="kbd">M</span></button>
      <button class="btn btn-sm" on:click={() => (importModalOpen = true)}>{$_("tracklist.import")}</button>
      <button class="btn btn-sm" on:click={() => (shiftOpen = true)}>{$_("tracklist.time_shift")}</button>
      <button class="btn btn-sm" on:click={runBulkResolve} disabled={bulkBusy}>{$_("tracklist.bulk_resolve")}</button>
    </div>
  </div>

  {#if bulkStatus}<p class="bulk-status">{bulkStatus}</p>{/if}

  {#if $tracklist.entries.length === 0}
    <p class="empty">{$_("tracklist.empty")}</p>
  {:else}
    <div>
      {#each $tracklist.entries as entry, idx (entry.id)}
        <div class="track-row" class:now={idx === currentIdx}>
          <button class="ts seek-cell" on:click={() => void seekInSet(slug, entry.start_seconds)}>{fmtDuration(entry.start_seconds)}</button>
          <span class="pos">{String(idx + 1).padStart(2, "0")}.</span>
          <div class="track-main">
            <div class="tn">{entry.raw_label}</div>
            {#if entry.edit_notes}<div class="ta">{entry.edit_notes}</div>{/if}
            {#if entry.track_id}
              <a class="other-sets" href={`/sets?track=${entry.track_id}&exclude=${encodeURIComponent(slug)}`}>{$_("browse.other_sets_with_track")}</a>
            {/if}
          </div>
          <span class="bpm-key"></span>
          <span class="badge" data-status={entry.status}>{entry.status}</span>
          <div class="actions">
            {#if entry.status === "raw"}
              <button class="btn btn-ghost btn-sm" on:click={() => (popoverEntry = entry)}>{$_("tracklist.resolve")}</button>
            {/if}
            <button class="btn btn-ghost btn-sm btn-icon" on:click={() => (drawerEntry = entry)} aria-label={$_("tracklist.edit_entry")}>✎</button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</section>

{#if drawerEntry}
  <TracklistEditDrawer {slug} entry={drawerEntry} on:close={() => (drawerEntry = null)} />
{/if}

{#if importModalOpen}
  <TracklistImportModal {slug} on:close={() => (importModalOpen = false)} />
{/if}

{#if shiftOpen}
  <TimeShiftDialog {slug} on:close={() => (shiftOpen = false)} />
{/if}

{#if popoverEntry}
  <ResolveCandidatesPopover
    {slug}
    entry={popoverEntry}
    on:close={() => (popoverEntry = null)}
  />
{/if}

<style>
  .tracks-section :global(.badge[data-status="raw"]) {
    color: var(--accent-warning);
    border-color: var(--accent-warning);
  }
  .tracks-section :global(.badge[data-status="resolved"]),
  .tracks-section :global(.badge[data-status="acoustid_confirmed"]) {
    color: var(--accent);
    border-color: var(--accent);
  }
  .track-row .ts.seek-cell {
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
    padding: 0;
    color: var(--accent-secondary, var(--accent));
  }
  .track-main { min-width: 0; }
  .other-sets { font-size: var(--ts-xs); color: var(--text-muted); }
  .other-sets:hover { color: var(--accent); }
  .track-main .tn { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bulk-status { margin: 0 var(--sp-8); padding: var(--sp-2) 0; color: var(--text-muted); font-size: var(--ts-sm); }
  .empty { margin: var(--sp-4) var(--sp-8); color: var(--text-muted); font-style: italic; }
</style>
