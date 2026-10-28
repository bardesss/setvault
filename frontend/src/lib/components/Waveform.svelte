<script lang="ts">
  import { _ } from "svelte-i18n";
  import { onMount, onDestroy } from "svelte";
  import WaveSurfer from "wavesurfer.js";
  import { listComments } from "#lib/api/comments.ts";
  import { player, seekInSet } from "#lib/stores/audio.ts";
  import { toPeaks } from "#lib/waveform-peaks.ts";

  export let slug: string;
  export let url: string;
  export let waveformUrl: string | null = null;
  export let fallbackDuration: number | undefined = undefined;

  let container: HTMLDivElement;
  let ws: WaveSurfer | null = null;
  let ready = false;
  let markers: Array<{ id: string; t: number; title: string }> = [];
  // A comment past the end (e.g. the set was swapped for a shorter copy) has no
  // spot on the waveform; placed at t/duration it would stretch the page sideways.
  $: shownMarkers = markers.filter((m) => m.t >= 0 && m.t <= duration);

  // Only the set that is actually loaded shows the engine's position; a page
  // for another set shows its own start and length.
  $: isCurrent = $player.set?.slug === slug;
  $: duration = isCurrent ? $player.duration : (fallbackDuration ?? 0);
  $: position = isCurrent ? $player.position : 0;
  $: loopStart = isCurrent ? $player.loopStart : null;
  $: loopEnd = isCurrent ? $player.loopEnd : null;

  // Drive the (otherwise idle) waveform's cursor/progress from the engine's
  // position — wavesurfer here is a picture, not the player.
  $: if (ws && ready && Number.isFinite(position)) {
    try { ws.setTime(position); } catch { /* not ready yet */ }
  }

  async function loadMarkers(): Promise<void> {
    try {
      const data = await listComments(slug);
      markers = data.items
        .filter((c) => c.position_seconds !== null && !c.deleted_at)
        .map((c) => ({ id: c.id, t: c.position_seconds as number,
          title: `${c.author.display_name ?? c.author.username}: ${(c.body_md ?? "").slice(0, 60)}` }));
    } catch { /* best-effort */ }
  }

  function tagCanvas(): boolean {
    if (!container) return false;
    for (const child of Array.from(container.children) as HTMLElement[]) {
      const shadow = child.shadowRoot;
      const canvases = shadow?.querySelector(".canvases");
      if (canvases && shadow) {
        canvases.setAttribute("data-test", "wavesurfer-canvas");
        if (!shadow.getElementById("e2e-canvas-pe")) {
          const style = document.createElement("style");
          style.id = "e2e-canvas-pe";
          style.textContent = ":host .canvases, :host .canvases > div, :host canvas { pointer-events: auto; }";
          shadow.appendChild(style);
        }
        return true;
      }
    }
    return false;
  }

  let destroyed = false;

  async function fetchPeaks(): Promise<ReturnType<typeof toPeaks>> {
    if (!waveformUrl) return null;
    try {
      const res = await fetch(waveformUrl, { credentials: "same-origin" });
      if (!res.ok) return null;
      return toPeaks(await res.json(), fallbackDuration);
    } catch {
      return null;
    }
  }

  onMount(() => {
    void init();
    void loadMarkers();
  });

  async function init(): Promise<void> {
    // Prefer precomputed peaks (no audio download/decode); fall back to
    // decoding the stream URL when they are missing or invalid.
    const pre = await fetchPeaks();
    if (destroyed) return;
    // Render with wavesurfer's OWN internal element. We never bind it to the
    // engine's <audio> and never play it — so ws.destroy() on unmount can't
    // touch live playback. The engine (stores/audio) is the single source of
    // truth for playback; this view's cursor is driven by the reactive
    // setTime above.
    ws = WaveSurfer.create({
      container,
      ...(pre ? { peaks: pre.peaks, duration: pre.duration } : { url }),
      waveColor: getComputedStyle(document.documentElement).getPropertyValue("--waveform-unplayed").trim() || "#6c707d",
      progressColor: getComputedStyle(document.documentElement).getPropertyValue("--waveform-played").trim() || "#00ffb2",
      cursorColor: getComputedStyle(document.documentElement).getPropertyValue("--playhead").trim() || "#00ffb2",
      cursorWidth: 1, barWidth: 2, barGap: 1, height: 96, normalize: true,
      autoplay: false,
    });
    ws.setMuted?.(true);
    if (!tagCanvas()) queueMicrotask(tagCanvas);
    ws.on("ready", () => { ready = true; tagCanvas(); });
    // click-to-seek: wavesurfer 'interaction' gives the clicked time
    ws.on("interaction", (t: number) => void seekInSet(slug, t));
  }

  onDestroy(() => { destroyed = true; ws?.destroy(); ws = null; });
</script>

<div class="wave-wrap">
  <div class="wave" bind:this={container} data-ready={ready ? "true" : "false"} aria-label={$_("player.waveform")}></div>
  {#if duration > 0 && loopStart !== null && loopEnd !== null}
    <div class="loop-band" data-test="loop-band"
      style="left: {(loopStart / duration) * 100}%; width: {((loopEnd - loopStart) / duration) * 100}%"
      aria-label={$_("player.loop_region")}></div>
  {/if}
  {#if duration > 0 && shownMarkers.length > 0}
    <div class="markers" aria-hidden="true">
      {#each shownMarkers as m (m.id)}
        <button type="button" class="marker" title={m.title}
          style="left: {(m.t / duration) * 100}%" on:click={() => void seekInSet(slug, m.t)}></button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .wave-wrap { position: relative; }
  .wave { width: 100%; min-height: 96px; background: var(--bg-surface);
    border: 1px solid var(--border-default); border-radius: var(--r-md); padding: var(--sp-2); }
  .loop-band { position: absolute; top: var(--sp-2); bottom: var(--sp-2);
    background: var(--accent-soft, rgba(0,255,178,0.14)); border-left: 2px solid var(--accent);
    border-right: 2px solid var(--accent); pointer-events: none; z-index: 1; }
  .markers { position: relative; height: 8px; margin-top: 2px; }
  .marker { position: absolute; top: 0; transform: translateX(-50%); width: 8px; height: 8px;
    border-radius: 50%; background: var(--accent); border: none; cursor: pointer; padding: 0; }
  .marker:hover { transform: translateX(-50%) scale(1.4); }
  @media (max-width: 600px) { .markers { height: 14px; } .marker { width: 14px; height: 14px; } }
</style>
