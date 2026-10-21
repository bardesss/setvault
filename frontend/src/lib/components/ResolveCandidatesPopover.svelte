<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { _ } from "svelte-i18n";
  import { acceptCandidate, idThis, resolveEntry, type ResolveCandidate } from "#lib/api/enrichment.ts";
  import type { TracklistEntry } from "#lib/api/tracklist.ts";
  import { upsertEntry } from "#lib/stores/tracklist.ts";

  export let slug: string;
  export let entry: TracklistEntry;

  type Mode = "metadata" | "fingerprint";
  let candidates: ResolveCandidate[] = [];
  let loading = true;
  let error: string | null = null;
  let mode: Mode = "metadata";
  const dispatch = createEventDispatcher();

  async function load(m: Mode) {
    mode = m;
    loading = true;
    error = null;
    candidates = [];
    try {
      candidates =
        m === "fingerprint"
          ? await idThis(slug, entry.id)
          : await resolveEntry(slug, entry.id);
    } catch (e) {
      error = e instanceof Error ? e.message : "error";
    } finally {
      loading = false;
    }
  }

  load("metadata");

  async function accept(c: ResolveCandidate) {
    const out = await acceptCandidate(slug, entry.id, c, mode === "fingerprint");
    upsertEntry({
      ...entry,
      status: out.status as TracklistEntry["status"],
      track_id: out.track_id,
    });
    dispatch("close");
  }

  function handleKeydown(ev: KeyboardEvent) {
    if (ev.key === "Escape") dispatch("close");
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<div class="backdrop" on:click={() => dispatch("close")} role="presentation"></div>
<section class="popover" role="dialog" aria-label={$_("resolve.heading")}>
  <header>
    <h3>{$_("resolve.heading")}: {entry.raw_label}</h3>
    <button on:click={() => dispatch("close")} aria-label="close">✕</button>
  </header>
  <nav class="modes">
    <button class:active={mode === "metadata"} on:click={() => load("metadata")}>
      {$_("resolve.mode_metadata")}
    </button>
    <button class:active={mode === "fingerprint"} on:click={() => load("fingerprint")}>
      {$_("resolve.mode_fingerprint")}
    </button>
  </nav>
  {#if loading}<p>{$_("resolve.loading")}</p>{/if}
  {#if error}<p class="error">{error}</p>{/if}
  {#if !loading && !error && candidates.length === 0}
    <p>{$_("resolve.no_candidates")}</p>
  {/if}
  <ul>
    {#each candidates as c, i (i)}
      <li>
        <span class="title">{c.artist_name} - {c.title}</span>
        <span class="conf mono">{(c.confidence * 100).toFixed(0)}%</span>
        <span class="src mono">{c.source_kind}</span>
        <button on:click={() => accept(c)}>{$_("resolve.accept")}</button>
      </li>
    {/each}
  </ul>
</section>

<style>
  .backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: var(--z-overlay); }
  .popover { position: fixed; top: 10vh; left: 50%; transform: translateX(-50%);
             width: min(620px, 92vw); max-height: 80vh; overflow-y: auto;
             background: var(--bg-elevated); padding: var(--sp-6); border-radius: var(--r-md);
             box-shadow: var(--shadow-lg);
             z-index: var(--z-modal); display: grid; gap: var(--sp-3); }
  header { display: flex; justify-content: space-between; align-items: center; }
  .modes { display: flex; gap: var(--sp-2); }
  .modes button { background: none; border: 1px solid var(--border-default);
                  border-radius: var(--r-sm); padding: var(--sp-1) var(--sp-3);
                  cursor: pointer; color: var(--text-muted); }
  .modes button.active { color: var(--text-default); background: var(--bg-hover); }
  ul { list-style: none; padding: 0; margin: 0; display: grid; gap: var(--sp-1); }
  li { display: grid; grid-template-columns: 1fr auto auto auto; gap: var(--sp-2);
       align-items: center; padding: var(--sp-2); }
  .conf, .src { font-family: var(--font-mono); color: var(--text-muted); }
  .error { color: var(--accent-error); }
</style>
