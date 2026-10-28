<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { _ } from "svelte-i18n";

  export let query: string = "";
  export let sort: string = "recent";
  export let sortOptions: { value: string; label: string }[] | null = null;
  $: options = sortOptions ?? [
    { value: "recent", label: $_("library.sort_recent") },
    { value: "title", label: $_("library.sort_title") },
    { value: "duration", label: $_("components.sort_duration") },
  ];
  export let view: "list" | "grid" = "list";

  const dispatch = createEventDispatcher<{
    query: string;
    sort: string;
    view: "list" | "grid";
  }>();

  function onInput(e: Event) {
    query = (e.target as HTMLInputElement).value;
    dispatch("query", query);
  }
  function onSort(e: Event) {
    sort = (e.target as HTMLSelectElement).value;
    dispatch("sort", sort);
  }
  function toggleView(next: "list" | "grid") {
    view = next;
    dispatch("view", view);
  }
</script>

<div class="filter-bar">
  <input
    type="search"
    bind:value={query}
    on:input={onInput}
    placeholder={$_("library.filter_placeholder")}
    aria-label={$_("library.filter_label")}
  />
  <select bind:value={sort} on:change={onSort} aria-label={$_("browse.sort_label")}>
    {#each options as opt (opt.value)}
      <option value={opt.value}>{opt.label}</option>
    {/each}
  </select>
  <div class="view-toggle" role="group" aria-label={$_("components.view_toggle")}>
    <button
      type="button"
      class:active={view === "list"}
      on:click={() => toggleView("list")}
      aria-pressed={view === "list"}
    >{$_("library.view_list")}</button>
    <button
      type="button"
      class:active={view === "grid"}
      on:click={() => toggleView("grid")}
      aria-pressed={view === "grid"}
    >{$_("library.view_grid")}</button>
  </div>
  <slot name="extra" />
</div>
