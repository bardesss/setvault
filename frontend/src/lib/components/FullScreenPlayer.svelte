<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import Waveform from "#lib/components/Waveform.svelte";
  import { listTracklist, type TracklistEntry } from "#lib/api/tracklist.ts";
  import { player, fullscreenOpen, toggle, seekBy, seekTo, prev, next, formatTime } from "#lib/stores/audio.ts";

  $: st = $player;
  $: artists = st.set?.artists?.map((a) => a.name).join(", ") ?? "";
  let entries: TracklistEntry[] = [];

  $: if (st.set) void loadEntries(st.set.slug);
  let loadedSlug: string | null = null;
  async function loadEntries(slug: string) {
    if (slug === loadedSlug) return;
    loadedSlug = slug;
    try { entries = (await listTracklist(slug)).slice().sort((a, b) => a.start_seconds - b.start_seconds); }
    catch { entries = []; }
  }

  $: currentIdx = entries.findIndex((e, i) =>
    e.start_seconds <= st.position && (!entries[i + 1] || entries[i + 1].start_seconds > st.position));

  function close() { fullscreenOpen.set(false); }
  function onKey(e: KeyboardEvent) { if (e.key === "Escape") close(); }
  onMount(() => window.addEventListener("keydown", onKey));
  onDestroy(() => { if (typeof window !== "undefined") window.removeEventListener("keydown", onKey); });
</script>

{#if $fullscreenOpen && st.set}
  <div class="fullscreen-player" role="dialog" aria-modal="true" aria-label="Now playing">
    <header class="fs-header">
      <button type="button" class="btn btn-icon" on:click={close} aria-label="Close">▾</button>
      <div style="min-width:0">
        <div class="fs-kicker">now playing</div>
        <div class="fs-title">{st.set.title} — {artists}</div>
      </div>
    </header>

    <div class="fs-body">
      <div class="lockscreen-art" aria-hidden="true">{(st.set.title ?? "").slice(0, 2).toUpperCase()}</div>
      <Waveform slug={st.set.slug} url={st.set.audio_stream_url} waveformUrl={st.set.waveform_url} />
      <div class="transport-time" style="text-align:center">
        <b>{formatTime(st.position)}</b><span class="div"> / </span>{formatTime(st.duration)}
      </div>
      <div class="fs-transport">
        <button type="button" class="btn btn-icon" on:click={prev} aria-label="Previous track">⏮</button>
        <button type="button" class="btn btn-icon" on:click={() => seekBy(-10)} aria-label="Back 10s">−10</button>
        <button type="button" class="play-large" on:click={toggle}
          data-test="fs-play-state" data-state={st.playing ? "playing" : "paused"}
          aria-label={st.playing ? "pause" : "play"}>
          {#if st.playing}
            <svg viewBox="0 0 16 16" width="20" height="20" fill="currentColor"><rect x="4" y="3" width="3" height="10"/><rect x="9" y="3" width="3" height="10"/></svg>
          {:else}
            <svg viewBox="0 0 16 16" width="20" height="20" fill="currentColor"><path d="M4 3l9 5-9 5z"/></svg>
          {/if}
        </button>
        <button type="button" class="btn btn-icon" on:click={() => seekBy(10)} aria-label="Forward 10s">+10</button>
        <button type="button" class="btn btn-icon" on:click={next} aria-label="Next track">⏭</button>
      </div>

      {#if entries.length}
        <div class="fs-tracklist" aria-label="Jump to track">
          {#each entries as e, i (e.id)}
            <button type="button" class:now={i === currentIdx} on:click={() => seekTo(e.start_seconds)}>
              <span class="ts">{formatTime(e.start_seconds)}</span>
              <span class="lbl">{e.raw_label}</span>
            </button>
          {/each}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .transport-time { font-family: var(--font-mono); color: var(--text-strong); font-variant-numeric: tabular-nums; }
  .fs-tracklist .lbl { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
