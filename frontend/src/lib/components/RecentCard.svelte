<script lang="ts">
  import { _ } from "svelte-i18n";
  export let slug: string;
  export let title: string;
  export let artist: string = "";
  export let venue: string = "";
  export let year: number | null = null;
  export let isNew: boolean = false;
</script>

<a class="recent-card" href={`/sets/${slug}`}>
  <div class="recent-cover" aria-hidden="true">
    {#if isNew}<span class="new-pip">{$_("cards.new")}</span>{/if}
  </div>
  <div class="ttl">{title}</div>
  <div class="meta">
    {#if artist}<b>{artist}</b>{/if}
    {#if venue} · {venue}{/if}
    {#if year} · {year}{/if}
  </div>
</a>

<style>
  .new-pip {
    position: absolute;
    top: var(--sp-2);
    left: var(--sp-2);
    font-family: var(--font-mono);
    font-size: var(--ts-xxs);
    text-transform: uppercase;
    background: var(--accent);
    color: var(--text-on-accent);
    padding: 2px 6px;
    border-radius: var(--r-pill);
  }
</style>
