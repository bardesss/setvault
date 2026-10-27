<script lang="ts">
  import { onMount } from "svelte";
  import Waveform from "#lib/components/Waveform.svelte";
  import type { SetDetail } from "#lib/api/sets.ts";
  import { player, load, toggle, playSingle, shouldAutoload, seekBy, setRate, clearLoop, formatTime, fullscreenOpen } from "#lib/stores/audio.ts";

  export let set: SetDetail;

  // Opening a set page never takes over a queue or a track that is playing.
  onMount(() => { if (shouldAutoload()) void load(set); });

  $: st = $player;
  $: isCurrent = st.set?.slug === set.slug;
  const RATES = [0.75, 1, 1.25, 1.5];
</script>

<div class="player">
  <section class="wave-stage">
    {#if !$fullscreenOpen}
      <Waveform slug={set.slug} url={set.audio_stream_url} waveformUrl={set.waveform_url} fallbackDuration={set.duration_seconds ?? undefined} />
    {/if}
  </section>

  <section class="transport-bar" aria-label="player controls">
    <div class="transport-time">
      <b>{formatTime(isCurrent ? st.position : 0)}</b>
      <span class="div">/</span>
      {formatTime(isCurrent && st.duration ? st.duration : (set.duration_seconds ?? 0))}
      {#if isCurrent && (st.loopStart !== null || st.loopEnd !== null)}
        <span class="loop-indicator mono" data-test="loop-indicator">
          Loop {st.loopStart !== null ? formatTime(st.loopStart) : "—"}…{st.loopEnd !== null ? formatTime(st.loopEnd) : "—"}
          <button type="button" class="loop-clear" on:click={clearLoop} aria-label="clear loop">×</button>
        </span>
      {/if}
    </div>

    <div class="transport-controls">
      <button type="button" class="btn btn-icon" on:click={() => seekBy(-10)} disabled={!isCurrent} aria-label="Back 10 seconds">−10</button>
      <button type="button" class="play-large" on:click={() => (isCurrent ? toggle() : void playSingle(set))}
        data-test="play-state" data-state={isCurrent && st.playing ? "playing" : "paused"}
        aria-label={isCurrent && st.playing ? "pause" : "play"}>
        {#if isCurrent && st.playing}
          <svg viewBox="0 0 16 16" width="20" height="20" fill="currentColor"><rect x="4" y="3" width="3" height="10"/><rect x="9" y="3" width="3" height="10"/></svg>
        {:else}
          <svg viewBox="0 0 16 16" width="20" height="20" fill="currentColor"><path d="M4 3l9 5-9 5z"/></svg>
        {/if}
      </button>
      <button type="button" class="btn btn-icon" on:click={() => seekBy(10)} disabled={!isCurrent} aria-label="Forward 10 seconds">+10</button>
    </div>

    <div class="transport-aux">
      <div class="speed-toggle" data-test="speed-control" role="group" aria-label="playback speed">
        {#each RATES as r}
          <button type="button" class:on={Math.abs(st.playbackRate - r) < 0.001} disabled={!isCurrent} on:click={() => setRate(r)}>{r}×</button>
        {/each}
      </div>
    </div>
  </section>
</div>

<style>
  .player { position: relative; display: block; }
  .wave-stage { position: relative; }
  .mono { font-variant-numeric: tabular-nums; }
  .loop-indicator { display: inline-flex; align-items: center; gap: var(--sp-1); margin-left: var(--sp-3);
    padding: 0 var(--sp-1); border: 1px solid var(--accent); border-radius: var(--r-sm);
    font-size: var(--ts-xs); color: var(--accent); }
  .loop-clear { background: transparent; border: none; color: inherit; cursor: pointer; padding: 0 2px; font-size: inherit; }
</style>
