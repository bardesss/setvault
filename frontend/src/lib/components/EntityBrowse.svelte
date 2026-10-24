<!-- Shared browse list for artists, parties, venues and series. -->
<script lang="ts">
  import { onDestroy } from "svelte";
  import { _ } from "svelte-i18n";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { listEntities, type EntityKind, type EntityListItem } from "#lib/api/catalog.ts";
  import { errorMessage } from "#lib/api/errors.ts";
  import { BROWSE_PAGE, type BrowseData } from "#lib/entityBrowse.ts";
  import { toast } from "#lib/stores/toast.ts";

  export let kind: EntityKind;
  export let title: string;
  export let data: BrowseData;

  // The URL (?q=&sort=) is the state: a change navigates, which reloads the
  // first page; "Load more" only appends to what the load returned.
  let items: EntityListItem[] = data.items;
  let total = data.total;
  let query = data.q;
  let sort: string = data.sort;
  let loading = false;
  $: {
    items = data.items;
    total = data.total;
    sort = data.sort;
  }

  function setParam(key: string, value: string) {
    const params = new URLSearchParams(page.url.searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    const qs = params.toString();
    goto(qs ? `?${qs}` : "?", { replace: true, reset: false });
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  function onQuery() {
    clearTimeout(timer);
    timer = setTimeout(() => setParam("q", query.trim()), 250);
  }
  onDestroy(() => clearTimeout(timer));

  async function loadMore() {
    loading = true;
    try {
      const r = await listEntities(kind, {
        q: data.q, sort: data.sort, limit: BROWSE_PAGE, offset: items.length,
      });
      const seen = new Set(items.map((i) => i.id));
      items = [...items, ...r.items.filter((i) => !seen.has(i.id))];
      total = r.total;
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head><title>{title} - SetVault</title></svelte:head>

<section class="browse">
  <h1>{title}</h1>
  <div class="bar">
    <input
      type="search"
      bind:value={query}
      on:input={onQuery}
      placeholder={$_("browse.search_placeholder")}
      aria-label={$_("browse.search_label")}
    />
    <select bind:value={sort} on:change={() => setParam("sort", sort === "name" ? "" : sort)} aria-label={$_("browse.sort_label")}>
      <option value="name">{$_("browse.sort_name")}</option>
      <option value="sets">{$_("browse.sort_sets")}</option>
      <option value="recent">{$_("browse.sort_recent")}</option>
    </select>
  </div>

  {#if items.length === 0}
    <p class="empty">{$_("browse.none")}</p>
  {:else}
    <ul class="list">
      {#each items as it (it.id)}
        <li>
          <a class="row" href={`/${kind}/${it.slug}`}>
            <span class="name">{it.name}</span>
            {#if it.hint}<span class="hint">{it.hint}</span>{/if}
            <span class="count">{$_("browse.sets_count", { values: { count: it.set_count } })}</span>
          </a>
        </li>
      {/each}
    </ul>
  {/if}

  <div class="pager">
    <p class="showing" data-testid="browse-count">{$_("browse.showing", { values: { shown: items.length, total } })}</p>
    {#if items.length < total}
      <button type="button" class="btn btn-ghost" disabled={loading} on:click={loadMore}>
        {$_("browse.load_more")}
      </button>
    {/if}
  </div>
</section>

<style>
  .browse { padding: var(--sp-6); display: grid; gap: var(--sp-4); max-width: 900px; }
  h1 { margin: 0; }
  .bar { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
  .bar input { flex: 1; min-width: 200px; }
  .list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--sp-1); }
  .row {
    display: flex; align-items: baseline; gap: var(--sp-3);
    padding: var(--sp-2); border: 1px solid var(--border-subtle); border-radius: var(--r-sm);
  }
  .name { font-weight: 600; }
  .hint { color: var(--text-faint); font-size: var(--ts-sm); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .count { margin-left: auto; color: var(--text-muted); font-family: var(--font-mono); font-size: var(--ts-xs); }
  .empty { color: var(--text-muted); font-family: var(--font-mono); text-align: center; padding: var(--sp-8); }
  .pager { display: grid; justify-items: center; gap: var(--sp-2); }
  .showing { margin: 0; font-size: var(--ts-sm); color: var(--text-muted); }
</style>
