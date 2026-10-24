<!-- frontend/src/lib/components/EntitySetsGrid.svelte -->
<script lang="ts">
  import { _ } from "svelte-i18n";
  import { getEntitySets, type EntityKind, type EntitySet } from "#lib/api/catalog.ts";
  import { toast } from "#lib/stores/toast.ts";
  import { errorMessage } from "#lib/api/errors.ts";

  export let kind: EntityKind;
  export let slug: string;
  export let sets: EntitySet[];
  export let total: number;

  let extra: EntitySet[] = [];
  let loading = false;
  // A new first page (another entity, or a reload) drops what was loaded on top.
  let first = sets;
  $: if (sets !== first) {
    first = sets;
    extra = [];
  }
  $: all = [...sets, ...extra.filter((e) => !sets.some((s) => s.slug === e.slug))];

  async function loadMore() {
    loading = true;
    try {
      const page = await getEntitySets(kind, slug, 50, all.length);
      extra = [...extra, ...page.items];
      total = page.total;
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      loading = false;
    }
  }
</script>

<ul class="entity-sets">
  {#each all as s (s.slug)}
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

{#if all.length < total}
  <button type="button" class="btn btn-ghost load-more" disabled={loading} on:click={loadMore}>
    {$_("browse.load_more")}
  </button>
{/if}

<style>
  .entity-sets { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--sp-1); }
  .row { display: grid; gap: 2px; padding: var(--sp-2); border: 1px solid var(--border-subtle); border-radius: var(--r-sm); }
  .title { font-weight: 600; }
  .meta { font-size: var(--ts-sm); color: var(--text-faint); }
  .load-more { justify-self: center; margin-top: var(--sp-3); }
</style>
