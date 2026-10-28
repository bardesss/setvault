<script lang="ts">
  import SetCard from "#lib/components/SetCard.svelte";
  import SetRow from "#lib/components/SetRow.svelte";
  import FilterSidebar from "#lib/components/FilterSidebar.svelte";
  import FilterBar from "#lib/components/FilterBar.svelte";
  import BulkActionToolbar from "#lib/components/BulkActionToolbar.svelte";
  import { goto, refreshAll } from "$app/navigation";
  import { page } from "$app/state";
  import { onDestroy } from "svelte";
  import { _ } from "svelte-i18n";
  import { session } from "#lib/stores/session.ts";
  import { listSets, type SetSummary } from "#lib/api/sets.ts";
  import { getTrack, type TrackInfo } from "#lib/api/catalog.ts";
  import { isTrackId } from "#lib/trackFilter.ts";
  import type { PageData } from "./$types";

  export let data: PageData;

  let query = data.filters.q;
  let sort: string = data.filters.sort || "recent";
  let view: "list" | "grid" = "grid";

  // The list lives in the URL: every filter/search/sort change navigates with
  // new params, which re-runs load and resets the list to the first page.
  let items: SetSummary[] = data.sets;
  let loadingMore = false;
  let moreError = false;
  $: items = data.sets;
  $: total = data.total;
  $: sort = data.filters.sort || "recent";

  $: isAdmin = $session?.role === "admin";
  $: filteredSets = items;

  function setParam(key: string, value: string) {
    const params = new URLSearchParams(page.url.searchParams.toString());
    if (value) params.set(key, value);
    else params.delete(key);
    const qs = params.toString();
    goto(qs ? `?${qs}` : "?", { replace: true, reset: false });
  }

  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  function onQuery() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setParam("q", query.trim()), 250);
  }
  onDestroy(() => clearTimeout(searchTimer));

  function onSort() {
    setParam("sort", sort);
  }

  // The track chip: only the id is in the URL, so fetch its title. A track
  // that can't be fetched (gone, or a malformed id) still gets a chip
  // ("Track: unknown") so the filter can always be removed.
  let trackInfo: TrackInfo | null = null;
  let trackUnknown = false;
  let trackFor = "";
  $: loadTrack(data.filters.track);
  async function loadTrack(id: string) {
    if (id === trackFor) return;
    trackFor = id;
    trackInfo = null;
    trackUnknown = false;
    if (!id) return;
    if (!isTrackId(id)) {
      trackUnknown = true;
      return;
    }
    try {
      const t = await getTrack(id);
      if (trackFor === id) trackInfo = t;
    } catch {
      if (trackFor === id) trackUnknown = true;
    }
  }
  $: chipLabel = trackInfo
    ? trackInfo.artist_name
      ? $_("browse.track_chip_artist", { values: { title: trackInfo.title, artist: trackInfo.artist_name } })
      : $_("browse.track_chip", { values: { title: trackInfo.title } })
    : trackUnknown
      ? $_("browse.track_chip_unknown")
      : "";

  async function loadMore() {
    loadingMore = true;
    moreError = false;
    try {
      const f = data.filters;
      const more = await listSets({
        q: f.q,
        tag: f.tag,
        year: f.year,
        venue_kind: f.venue_kind,
        sort: f.sort,
        track: f.track,
        exclude: f.exclude,
        limit: data.limit,
        offset: items.length,
      });
      const seen = new Set(items.map((s) => s.id));
      items = [...items, ...more.items.filter((s) => !seen.has(s.id))];
    } catch {
      moreError = true;
    } finally {
      loadingMore = false;
    }
  }

  // Selection by set id. Reassigning the Set forces reactivity.
  let selected = new Set<string>();
  let lastClickedIndex: number | null = null;

  function toggle(id: string, index: number, withShift: boolean) {
    if (withShift && lastClickedIndex !== null) {
      const [a, b] = [lastClickedIndex, index].sort((x, y) => x - y);
      const target = !selected.has(id);
      const next = new Set(selected);
      for (let i = a; i <= b; i++) {
        const setId = filteredSets[i]?.id;
        if (!setId) continue;
        if (target) next.add(setId);
        else next.delete(setId);
      }
      selected = next;
    } else {
      const next = new Set(selected);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      selected = next;
    }
    lastClickedIndex = index;
  }

  // A new result set (filter, sort, refresh) invalidates the selection.
  $: if (data) {
    selected = new Set();
    lastClickedIndex = null;
  }

  function toggleAll() {
    if (selected.size === filteredSets.length) {
      selected = new Set();
    } else {
      selected = new Set(filteredSets.map((s) => s.id));
    }
  }

  function clearSelection() {
    selected = new Set();
    lastClickedIndex = null;
  }

  async function afterBulkAction(_action: string) {
    clearSelection();
    await refreshAll();
  }
</script>

<svelte:head><title>{$_("library.title")} - SetVault</title></svelte:head>

<FilterBar
  bind:query
  bind:sort
  bind:view
  on:query={onQuery}
  on:sort={onSort}
  sortOptions={[
    { value: "recent", label: $_("library.sort_recent") },
    { value: "date", label: $_("library.sort_date") },
    { value: "title", label: $_("library.sort_title") },
    { value: "duration", label: $_("library.sort_duration") },
  ]}
/>

<section class="library-body">
  {#if trackInfo || trackUnknown}
    <div class="chips">
      <span class="chip" data-testid="track-chip">
        {chipLabel}
        <button type="button" aria-label={$_("browse.remove_track_filter")} on:click={() => setParam("track", "")}>×</button>
      </span>
    </div>
  {/if}
  {#if isAdmin && selected.size > 0}
    <BulkActionToolbar
      selectedIds={Array.from(selected)}
      onCleared={clearSelection}
      onSubmitted={afterBulkAction}
    />
  {/if}

  <div class="layout">
    <FilterSidebar
      tags={data.facets.tags}
      venueKinds={data.facets.venue_kinds}
      years={data.facets.years}
    />
    <div>
      {#if isAdmin && filteredSets.length > 0}
        <p class="select-all-row">
          <label>
            <input
              type="checkbox"
              checked={selected.size === filteredSets.length}
              indeterminate={selected.size > 0 && selected.size < filteredSets.length}
              on:change={toggleAll}
            />
            {$_("library.select_all", { values: { selected: selected.size, total: filteredSets.length } })}
          </label>
        </p>
      {/if}

      {#if filteredSets.length === 0}
        <div class="empty">{$_("library.no_match")}</div>
      {:else if view === "list"}
        <div class="list">
          {#each filteredSets as s (s.slug)}
            <SetRow
              slug={s.slug}
              title={s.title}
              artist={(s.artists ?? []).map((a) => a.name).join(", ")}
              durationSeconds={s.duration_seconds ?? null}
              date={s.date ?? null}
            />
          {/each}
        </div>
      {:else}
        <div class="grid">
          {#each filteredSets as s, i (s.slug)}
            {#if isAdmin}
              <div class="card-wrap" class:selected={selected.has(s.id)}>
                <button
                  type="button"
                  class="select-toggle"
                  aria-label={$_("library.toggle_selection")}
                  aria-pressed={selected.has(s.id)}
                  on:click|preventDefault={(e) => toggle(s.id, i, e.shiftKey)}
                >
                  <span class="checkbox" data-checked={selected.has(s.id)}></span>
                </button>
                <SetCard set={s} actions={false} />
              </div>
            {:else}
              <SetCard set={s} />
            {/if}
          {/each}
        </div>
      {/if}

      <div class="pager">
        <p class="count" data-testid="library-count">
          {$_("library.showing", { values: { shown: items.length, total } })}
        </p>
        {#if items.length < total}
          <button type="button" class="load-more" disabled={loadingMore} on:click={loadMore}>
            {$_("library.load_more")}
          </button>
        {/if}
        {#if moreError}
          <p class="more-error" role="alert">{$_("library.load_more_failed")}</p>
        {/if}
      </div>
    </div>
  </div>
</section>

<style>
  .library-body {
    padding: var(--sp-4) var(--sp-6);
    display: grid;
    gap: var(--sp-4);
  }
  .layout {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr);
    gap: var(--sp-4);
  }
  @media (max-width: 760px) {
    .layout { grid-template-columns: 1fr; }
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(280px, 100%), 1fr));
    gap: var(--sp-3);
  }
  .list { display: grid; }
  .pager {
    display: grid;
    justify-items: center;
    gap: var(--sp-2);
    padding: var(--sp-4) 0;
  }
  .count { margin: 0; font-size: var(--ts-sm); color: var(--text-muted); }
  .load-more {
    padding: var(--sp-2) var(--sp-4);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    color: inherit;
    cursor: pointer;
  }
  .empty {
    padding: var(--sp-8);
    text-align: center;
    color: var(--text-muted);
    font-family: var(--font-mono);
  }
  .select-all-row { margin: 0 0 var(--sp-2) 0; font-size: var(--ts-sm); }
  .select-all-row label { display: inline-flex; align-items: center; gap: var(--sp-1); cursor: pointer; }
  .card-wrap {
    position: relative;
    border-radius: var(--r-md);
    outline: 2px solid transparent;
    outline-offset: -2px;
    transition: outline-color 100ms;
  }
  .card-wrap.selected { outline-color: var(--accent); }
  .select-toggle {
    position: absolute;
    top: var(--sp-2);
    left: var(--sp-2);
    z-index: 5;
    width: 28px;
    height: 28px;
    border-radius: var(--r-sm);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    cursor: pointer;
    display: grid;
    place-items: center;
    padding: 0;
  }
  .checkbox {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid var(--border-default);
    border-radius: 3px;
  }
  .checkbox[data-checked="true"] {
    background: var(--accent);
    border-color: var(--accent);
  }
  @media (max-width: 600px) {
    .library-body { padding: var(--sp-3); }
    .grid { grid-template-columns: 1fr; }
  }
  .chips { display: flex; gap: var(--sp-2); }
  .chip {
    display: inline-flex; align-items: center; gap: var(--sp-2);
    padding: 2px var(--sp-3); border: 1px solid var(--accent); border-radius: 999px;
    color: var(--accent); font-size: var(--ts-sm);
  }
  .chip button { background: none; border: none; color: inherit; cursor: pointer; padding: 0; font-size: var(--ts-md, 1em); line-height: 1; }
  .more-error { color: var(--accent-error); font-size: var(--ts-sm); margin: 0; }
</style>
