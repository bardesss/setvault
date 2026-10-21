<script lang="ts">
  import { player, fullscreenOpen, toggle, formatTime } from "#lib/stores/audio.ts";

  $: st = $player;
  $: pct = st.duration > 0 ? Math.min(100, (st.position / st.duration) * 100) : 0;
  $: cover = (st.set?.title ?? "").slice(0, 2).toUpperCase();
  $: artists = st.set?.artists?.map((a) => a.name).join(", ") ?? "";

  function open() { fullscreenOpen.set(true); }
</script>

{#if st.set}
  <div class="m-bottom-sheet" role="region" aria-label="now playing">
    <div class="m-sheet-progress"><div class="fill" style="width: {pct}%"></div></div>
    <div class="m-sheet-row">
      <button class="m-sheet-cover" on:click={open} aria-label="Open full-screen player">{cover}</button>
      <button class="m-sheet-meta" on:click={open}>
        <div class="m-sheet-title">{st.set.title}</div>
        <div class="m-sheet-sub">{artists}</div>
      </button>
      <div class="m-sheet-controls">
        <span class="time mono" aria-hidden="true">{formatTime(st.position)} / {formatTime(st.duration)}</span>
        <button type="button" class="btn btn-icon" on:click={toggle}
          data-test="mini-play-state" data-state={st.playing ? "playing" : "paused"}
          aria-label={st.playing ? "pause" : "play"}>
          {#if st.playing}
            <svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor"><rect x="4" y="3" width="3" height="10"/><rect x="9" y="3" width="3" height="10"/></svg>
          {:else}
            <svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor"><path d="M4 3l9 5-9 5z"/></svg>
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .time { font-family: var(--font-mono); font-size: var(--ts-xs); color: var(--text-muted);
    font-variant-numeric: tabular-nums; }
  @media (max-width: 600px) { .time { display: none; } }
</style>
