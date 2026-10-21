<script lang="ts">
  import type { SetSummary } from "#lib/api/sets.ts";
  export let set: SetSummary;
</script>

<a class="set-card" href={`/sets/${set.slug}`}>
  <div class="ttl">{set.title}</div>
  <div class="meta">
    {#each set.artists as a (a.id)}<span>{a.name}</span>{/each}
    {#if set.date}<time>{set.date}</time>{/if}
  </div>
</a>

<style>
  .set-card {
    display: grid;
    gap: var(--sp-1);
    padding: var(--sp-3) var(--sp-4);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    text-decoration: none;
    color: inherit;
  }
  .ttl { font-weight: 700; }
  .meta {
    display: flex;
    gap: var(--sp-2);
    color: var(--text-faint);
    font-size: var(--ts-sm);
  }
</style>
