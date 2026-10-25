<script lang="ts">
  import { _ } from "svelte-i18n";
  import type { PageData } from "./$types";
  import { fmtDuration } from "#lib/format.ts";

  export let data: PageData;
  $: set = data.set;

</script>

<svelte:head><title>{set.title} — SetVault</title></svelte:head>

<div class="embed-chrome">
  <header class="embed-header">
    <a class="brand" href="/" target="_top" aria-label="SetVault home">
      <span class="brand-dot"></span>
      <span class="brand-name">SETVAULT</span>
    </a>
    <h1 class="embed-title">{set.title}</h1>
  </header>

  <div class="embed-body">
    <audio controls preload="metadata" src={set.audio_url}></audio>

    {#if set.tracklist.length > 0}
      <ol class="tracklist">
        {#each set.tracklist as t (t.position)}
          <li>
            <span class="ts">{t.start_seconds == null ? "" : fmtDuration(t.start_seconds)}</span>
            {t.label ?? `Track ${t.position}`}
          </li>
        {/each}
      </ol>
    {/if}
  </div>

  <footer class="embed-footer">
    <span>Embedded from SetVault</span>
    <a href={`/sets/${set.slug}`} target="_top">{$_("embed.open_in_setvault")} →</a>
  </footer>
</div>

<style>
  .embed-title {
    font-weight: 700;
    color: var(--text-strong);
    flex: 1;
    text-align: center;
    font-size: var(--ts-md);
    margin: 0;
    letter-spacing: var(--ls-tight);
  }
  audio { width: 100%; margin-bottom: var(--sp-3); }
  .tracklist {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 4px;
    font-size: var(--ts-sm);
  }
  .ts {
    font-family: var(--font-mono);
    color: var(--text-faint);
    margin-right: var(--sp-2);
  }
  .embed-footer a { color: var(--accent); text-decoration: none; }
  .embed-footer a:hover { text-decoration: underline; }
</style>
