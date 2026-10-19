<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { _ } from "svelte-i18n";
  import FilterBar from "$lib/components/FilterBar.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import { searchSources, type SourceCandidate } from "$lib/api/ingest_sources";
  import { submitUrl } from "$lib/api/url_rip";

  type SearchResults = {
    sets: { slug: string; title: string }[];
    artists: { slug: string; name: string }[];
  };

  let query = "";
  let loading = false;
  let results: SearchResults | null = null;
  let initialized = false;

  let mode: "library" | "sources" = "library";
  let sourceQuery = "";
  let candidates: SourceCandidate[] = [];
  let erroredSources: string[] = [];
  let searching = false;
  let sourceError: string | null = null;
  let ingesting: Record<string, boolean> = {};

  const SOURCE_LABELS: Record<string, string> = {
    youtube: "YouTube",
    soundcloud: "SoundCloud",
    mixcloud: "Mixcloud",
    internet_archive: "Internet Archive",
    bandcamp: "Bandcamp",
  };
  const sourceLabel = (kind: string) => SOURCE_LABELS[kind] ?? kind;

  async function runSourceSearch() {
    if (!sourceQuery.trim()) {
      candidates = [];
      erroredSources = [];
      return;
    }
    searching = true;
    sourceError = null;
    try {
      const result = await searchSources(sourceQuery.trim());
      candidates = result.items;
      erroredSources = result.errored_sources;
    } catch (e) {
      sourceError = $_("sources.search_failed");
    } finally {
      searching = false;
    }
  }

  async function ingest(c: SourceCandidate) {
    ingesting[c.external_id] = true;
    ingesting = ingesting;
    try {
      await submitUrl(c.webpage_url, "source_search");
      candidates = candidates.map((x) =>
        x.external_id === c.external_id ? { ...x, already_in_library: true } : x,
      );
    } catch (e) {
      sourceError = e instanceof Error ? e.message : $_("sources.ingest_failed");
    } finally {
      ingesting[c.external_id] = false;
      ingesting = ingesting;
    }
  }

  onMount(() => {
    const q = $page.url.searchParams.get("q") ?? "";
    query = q;
    initialized = true;
    if (q) runSearch(q);
  });

  let timer: ReturnType<typeof setTimeout> | null = null;
  function onQueryEvent(e: CustomEvent<string>) {
    const next = e.detail;
    query = next;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => runSearch(next), 200);
  }

  async function runSearch(q: string) {
    goto(`/search?q=${encodeURIComponent(q)}`, {
      keepFocus: true,
      noScroll: true,
      replaceState: true,
    });
    if (!q) {
      results = null;
      return;
    }
    loading = true;
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`, {
        credentials: "include",
      });
      if (!res.ok) {
        results = null;
        return;
      }
      results = (await res.json()) as SearchResults;
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head><title>Search — SetVault</title></svelte:head>

<FilterBar
  bind:query
  on:query={onQueryEvent}
  sortOptions={[{ value: "relevance", label: "Relevance" }]}
  sort="relevance"
  view="list"
/>

<section class="search-body">
  <div class="tab-strip" role="tablist">
    <button
      type="button"
      role="tab"
      class="tab"
      class:active={mode === "library"}
      on:click={() => (mode = "library")}
    >
      {$_("sources.tab_library")}
    </button>
    <button
      type="button"
      role="tab"
      class="tab"
      class:active={mode === "sources"}
      on:click={() => (mode = "sources")}
    >
      {$_("sources.tab_sources")}
    </button>
  </div>

  {#if mode === "sources"}
    <form on:submit|preventDefault={runSourceSearch} class="source-search">
      <input
        type="search"
        bind:value={sourceQuery}
        placeholder={$_("sources.search_placeholder")}
      />
      <button
        type="submit"
        class="btn"
        disabled={searching}
        aria-label={$_("sources.search_submit")}>{$_("sources.search_submit")}</button
      >
    </form>
    {#if sourceError}<p class="admin-msg is-error" role="alert">{sourceError}</p>{/if}
    {#if erroredSources.length > 0}
      <p class="admin-msg is-warn" role="status">
        {$_("sources.partial_unavailable", {
          values: { sources: erroredSources.map(sourceLabel).join(", ") },
        })}
      </p>
    {/if}
    {#if !searching && candidates.length === 0 && sourceQuery}
      <EmptyState message={$_("sources.no_results")} />
    {:else}
      <ul class="candidate-list">
        {#each candidates as c (c.external_id)}
          <li class="candidate">
            {#if c.thumbnail_url}<img src={c.thumbnail_url} alt="" loading="lazy" />{/if}
            <div class="meta">
              <strong>{c.title}</strong>
              <span class="muted">{c.uploader ?? ""}</span>
              <span class="source-chip">{sourceLabel(c.source_kind)}</span>
              <span class="source-chip quality-chip" data-tier={c.expected_tier ?? "unknown"}
                >{$_(`sources.quality.${c.expected_tier ?? "unknown"}`)}</span
              >
            </div>
            {#if c.already_in_library}
              <span class="badge">{$_("sources.in_library")}</span>
            {:else}
              <button
                type="button"
                class="btn btn-sm"
                disabled={ingesting[c.external_id]}
                on:click={() => ingest(c)}
              >
                {ingesting[c.external_id] ? $_("sources.ingesting") : $_("sources.ingest")}
              </button>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}

  {#if mode === "library"}
    {#if !initialized}
      <p class="hint">Loading…</p>
    {:else if !query}
      <p class="hint">Type to search artists, sets, parties…</p>
    {:else if loading}
      <p class="hint">Searching…</p>
    {:else if !results || (results.sets.length === 0 && results.artists.length === 0)}
      <p class="hint">No matches for "{query}".</p>
    {:else}
      {#if results.sets.length}
        <h2 class="group">Sets</h2>
        <ul class="result-list">
          {#each results.sets as s (s.slug)}
            <li><a href={`/sets/${s.slug}`}>{s.title}</a></li>
          {/each}
        </ul>
      {/if}
      {#if results.artists.length}
        <h2 class="group">Artists</h2>
        <ul class="result-list">
          {#each results.artists as a (a.slug)}
            <li><a href={`/artists/${a.slug}`}>{a.name}</a></li>
          {/each}
        </ul>
      {/if}
    {/if}
  {/if}
</section>

<style>
  .search-body { padding: var(--sp-4) var(--sp-8) var(--sp-8); }
  .hint {
    padding: var(--sp-8);
    text-align: center;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: var(--ts-md);
  }
  .group {
    font-size: var(--ts-md);
    font-family: var(--font-mono);
    text-transform: uppercase;
    letter-spacing: var(--ls-uppercase);
    color: var(--text-faint);
    margin: var(--sp-5) 0 var(--sp-2);
  }
  .group:first-of-type { margin-top: 0; }
  .result-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: var(--sp-2);
  }
  .result-list a {
    color: var(--text-default);
    text-decoration: none;
    padding: var(--sp-2) var(--sp-3);
    border-radius: var(--r-sm);
    display: block;
  }
  .result-list a:hover { background: var(--bg-surface); color: var(--accent); }

  .source-search { display: flex; gap: var(--sp-2); margin: var(--sp-3) 0; }
  .source-search input {
    flex: 1;
    padding: var(--sp-2) var(--sp-3);
    background: var(--bg-base);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    color: var(--text-default);
    font: inherit;
  }
  .candidate-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    gap: var(--sp-2);
  }
  .candidate {
    display: grid;
    grid-template-columns: 96px 1fr max-content;
    gap: var(--sp-3);
    align-items: center;
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    padding: var(--sp-2);
  }
  .candidate img {
    width: 96px;
    height: 54px;
    object-fit: cover;
    border-radius: var(--r-sm);
  }
  .candidate .meta { display: grid; gap: 2px; min-width: 0; }
  .candidate .meta strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); }
  .badge { color: var(--accent); font-size: var(--ts-sm); }
  .source-chip {
    align-self: start;
    font-size: var(--ts-sm);
    color: var(--text-faint);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    padding: 0 var(--sp-2);
  }
  .admin-msg.is-warn { color: var(--text-faint); }
  @media (max-width: 600px) {
    .candidate { grid-template-columns: 64px 1fr; }
    .candidate img { width: 64px; height: 36px; }
  }
</style>
