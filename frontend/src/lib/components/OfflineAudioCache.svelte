<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import {
    clearAudioCache,
    offline,
    refreshUsage,
    setCap,
  } from "#lib/stores/offline.ts";

  interface Preset {
    label: string;
    bytes: number;
  }

  const PRESETS: Preset[] = [
    { label: "500 MB", bytes: 500 * 1024 * 1024 },
    { label: "1 GB",   bytes: 1024 * 1024 * 1024 },
    { label: "5 GB",   bytes: 5 * 1024 * 1024 * 1024 },
    { label: "10 GB",  bytes: 10 * 1024 * 1024 * 1024 },
  ];

  let clearing = false;

  onMount(refreshUsage);

  function fmtBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
    return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  async function doClear() {
    clearing = true;
    try {
      await clearAudioCache();
    } finally {
      clearing = false;
    }
  }
</script>

<section class="card cache">
  <h2>{$_("pwa.cache.heading")}</h2>
  <p class="muted">{$_("pwa.cache.description")}</p>
  <p class="usage" data-test="offline-usage">
    {fmtBytes($offline.usedBytes)} / {fmtBytes($offline.capBytes)}
    {#if $offline.quotaBytes}
      <span class="quota">
        ({$_("pwa.cache.quota")}: {fmtBytes($offline.quotaBytes)})
      </span>
    {/if}
  </p>
  <div class="presets" role="radiogroup" aria-label={$_("pwa.cache.heading")}>
    {#each PRESETS as p (p.bytes)}
      <button
        type="button"
        role="radio"
        aria-checked={$offline.capBytes === p.bytes}
        class:active={$offline.capBytes === p.bytes}
        on:click={() => setCap(p.bytes)}
      >
        {p.label}
      </button>
    {/each}
  </div>
  <button type="button" class="clear" on:click={doClear} disabled={clearing}>
    {clearing ? "…" : $_("pwa.cache.clear")}
  </button>
</section>

<style>
  .cache { display: grid; gap: var(--sp-2); }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
  .usage { font-family: var(--font-mono); color: var(--text-muted); margin: 0; }
  .quota { font-size: var(--ts-sm); }
  .presets { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
  .presets button {
    padding: var(--sp-1) var(--sp-2);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    background: var(--bg-surface);
    color: var(--text-default);
    cursor: pointer;
    min-height: 36px;
  }
  .presets button.active {
    background: var(--accent);
    color: var(--text-on-accent);
    border-color: var(--accent);
  }
  .clear {
    justify-self: start;
    padding: var(--sp-1) var(--sp-2);
    border: 1px solid var(--border-default);
    background: transparent;
    color: inherit;
    border-radius: var(--r-sm);
    cursor: pointer;
  }
  .clear:disabled { opacity: 0.5; cursor: progress; }
  @media (max-width: 600px) {
    .presets button { min-height: 44px; flex: 1; }
  }
</style>
