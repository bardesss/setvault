<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { toStore } from "svelte/store";
  import { _ } from "svelte-i18n";

  export let tags: { slug: string; name: string; count?: number }[] = [];
  export let venueKinds: string[] = [];
  export let years: number[] = [];

  // Legacy `$:` statements don't track rune state like `page`; a store does.
  const pageUrl = toStore(() => page.url);

  function setParam(key: string, value: string | null) {
    const params = new URLSearchParams(page.url.searchParams.toString());
    if (value && value !== "") params.set(key, value);
    else params.delete(key);
    const qs = params.toString();
    goto(qs ? `?${qs}` : "?", { replace: true, reset: false });
  }

  function onSelect(key: string, event: Event) {
    const target = event.currentTarget as HTMLSelectElement;
    setParam(key, target.value);
  }

  $: currentTag = $pageUrl.searchParams.get("tag") ?? "";
  $: currentVenueKind = $pageUrl.searchParams.get("venue_kind") ?? "";
  $: currentYear = $pageUrl.searchParams.get("year") ?? "";
</script>

<aside class="filter-sidebar" aria-label={$_("library.filters")}>
  <label>
    <span>{$_("library.tag")}</span>
    <select value={currentTag} on:change={(e) => onSelect("tag", e)}>
      <option value="">{$_("library.all")}</option>
      {#each tags as t (t.slug)}<option value={t.slug}>{t.name}{t.count !== undefined ? ` (${t.count})` : ""}</option>{/each}
    </select>
  </label>

  <label>
    <span>{$_("library.venue_kind")}</span>
    <select value={currentVenueKind} on:change={(e) => onSelect("venue_kind", e)}>
      <option value="">{$_("library.all")}</option>
      {#each venueKinds as k (k)}<option value={k}>{k}</option>{/each}
    </select>
  </label>

  <label>
    <span>{$_("library.year")}</span>
    <select value={currentYear} on:change={(e) => onSelect("year", e)}>
      <option value="">{$_("library.all")}</option>
      {#each years as y (y)}<option value={String(y)}>{y}</option>{/each}
    </select>
  </label>
</aside>

<style>
  .filter-sidebar {
    display: grid;
    gap: var(--sp-3);
    padding: var(--sp-4);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
  }
  label {
    display: grid;
    gap: var(--sp-1);
    font-size: var(--ts-sm);
    color: var(--text-muted);
  }
  select {
    padding: var(--sp-2);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    color: inherit;
  }
</style>
