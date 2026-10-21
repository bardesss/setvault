<!-- frontend/src/lib/components/EntitySetsGrid.svelte -->
<script lang="ts">
  import type { EntitySet } from "#lib/api/catalog.ts";
  export let sets: EntitySet[];
</script>

<ul class="entity-sets">
  {#each sets as s (s.slug)}
    <li>
      <a class="row" href={`/sets/${s.slug}`}>
        <span class="title">{s.title}</span>
        <span class="meta">
          {s.artists.map((a) => a.name).join(", ")}
          {#if s.venue}· {s.venue.name}{/if}
          {#if s.date}· {s.date}{/if}
        </span>
      </a>
    </li>
  {/each}
</ul>

<style>
  .entity-sets { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--sp-1); }
  .row { display: grid; gap: 2px; padding: var(--sp-2); border: 1px solid var(--border-subtle); border-radius: var(--r-sm); }
  .title { font-weight: 600; }
  .meta { font-size: var(--ts-sm); color: var(--text-faint); }
</style>
