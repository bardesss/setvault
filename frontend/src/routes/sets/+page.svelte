<script lang="ts">
  import SetCard from "#lib/components/SetCard.svelte";
  import SetRow from "#lib/components/SetRow.svelte";
  import FilterSidebar from "#lib/components/FilterSidebar.svelte";
  import FilterBar from "#lib/components/FilterBar.svelte";
  import BulkActionToolbar from "#lib/components/BulkActionToolbar.svelte";
  import { invalidateAll } from "$app/navigation";
  import { session } from "#lib/stores/session.ts";
  import type { PageData } from "./$types";

  export let data: PageData;

  let query = "";
  let sort: string = "recent";
  let view: "list" | "grid" = "grid";

  $: tagOptions = Array.from(
    new Set(data.sets.flatMap((s) => s.tags)),
  ).sort();
  $: yearOptions = Array.from(
    new Set(
      data.sets
        .map((s) => (s.date ? Number.parseInt(s.date.slice(0, 4), 10) : null))
        .filter((y): y is number => y !== null && !Number.isNaN(y)),
    ),
  ).sort((a, b) => b - a);

  $: isAdmin = $session?.role === "admin";

  $: filteredSets = (() => {
    let out = data.sets;
    if (query) {
      const q = query.toLowerCase();
      out = out.filter((s) => {
        const artistNames = (s.artists ?? []).map((a) => a.name).join(" ");
        return (
          s.title.toLowerCase().includes(q) ||
          artistNames.toLowerCase().includes(q)
        );
      });
    }
    if (sort === "title") {
      out = out.slice().sort((a, b) => a.title.localeCompare(b.title));
    } else if (sort === "duration") {
      out = out.slice().sort((a, b) => (b.duration_seconds ?? 0) - (a.duration_seconds ?? 0));
    }
    return out;
  })();

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
    await invalidateAll();
  }
</script>

<svelte:head><title>Library - SetVault</title></svelte:head>

<FilterBar
  bind:query
  bind:sort
  bind:view
  sortOptions={[
    { value: "recent", label: "Recently added" },
    { value: "title", label: "Title A→Z" },
    { value: "duration", label: "Longest first" },
  ]}
/>

<section class="library-body">
  {#if isAdmin && selected.size > 0}
    <BulkActionToolbar
      selectedIds={Array.from(selected)}
      onCleared={clearSelection}
      onSubmitted={afterBulkAction}
    />
  {/if}

  <div class="layout">
    <FilterSidebar tags={tagOptions} venueKinds={[]} years={yearOptions} />
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
            Select all ({selected.size}/{filteredSets.length})
          </label>
        </p>
      {/if}

      {#if filteredSets.length === 0}
        <div class="empty">No sets match.</div>
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
                  aria-label="Toggle selection"
                  aria-pressed={selected.has(s.id)}
                  on:click|preventDefault={(e) => toggle(s.id, i, e.shiftKey)}
                >
                  <span class="checkbox" data-checked={selected.has(s.id)}></span>
                </button>
                <SetCard set={s} />
              </div>
            {:else}
              <SetCard set={s} />
            {/if}
          {/each}
        </div>
      {/if}
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
    grid-template-columns: 240px 1fr;
    gap: var(--sp-4);
  }
  @media (max-width: 760px) {
    .layout { grid-template-columns: 1fr; }
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: var(--sp-3);
  }
  .list { display: grid; }
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
</style>
