<script lang="ts">
  import { onDestroy, onMount, tick } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { _ } from "svelte-i18n";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { searchSources, type SourceCandidate } from "#lib/api/ingest_sources.ts";
  import { isRipActive, listMyRipJobs, submitUrl, type RipJob } from "#lib/api/url_rip.ts";

  type SearchResults = {
    sets: { slug: string; title: string }[];
    artists: { slug: string; name: string }[];
  };

  // One query drives both tabs: the library searches as you type, the
  // external sources (slow, rate-limited) only on submit or tab switch.
  let query = "";
  let mode: "library" | "sources" = "library";
  let input: HTMLInputElement;

  let loading = false;
  let results: SearchResults | null = null;
  let initialized = false;

  let lastSourceQuery = "";
  let candidates: SourceCandidate[] = [];
  let erroredSources: string[] = [];
  let throttledSources: string[] = [];
  let searching = false;
  let sourceError: string | null = null;
  let submitting: Record<string, boolean> = {};
  // Rip job per candidate external_id, polled until it reaches ready/failed.
  let rips: Record<string, RipJob> = {};
  let pollTimer: ReturnType<typeof setTimeout> | null = null;

  const SOURCE_LABELS: Record<string, string> = {
    youtube: "YouTube",
    soundcloud: "SoundCloud",
    mixcloud: "Mixcloud",
    internet_archive: "Internet Archive",
    bandcamp: "Bandcamp",
  };
  const sourceLabel = (kind: string) => SOURCE_LABELS[kind] ?? kind;

  function syncUrl() {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (mode === "sources") params.set("tab", "sources");
    const qs = params.toString();
    goto(`/search${qs ? `?${qs}` : ""}`, { reset: false, replace: true });
  }

  async function runSourceSearch() {
    const q = query.trim();
    lastSourceQuery = q;
    if (!q) {
      candidates = [];
      erroredSources = [];
      throttledSources = [];
      return;
    }
    searching = true;
    sourceError = null;
    try {
      const result = await searchSources(q);
      candidates = result.items;
      erroredSources = result.errored_sources;
      throttledSources = result.throttled_kinds;
    } catch (e) {
      sourceError = $_("sources.search_failed");
    } finally {
      searching = false;
    }
  }

  function setMode(next: "library" | "sources") {
    mode = next;
    if (mode === "library") {
      runSearch(query);
    } else {
      syncUrl();
      if (query.trim() && query.trim() !== lastSourceQuery) runSourceSearch();
    }
    input?.focus();
  }

  async function pollRips() {
    pollTimer = null;
    const tracked = Object.entries(rips).filter(([, j]) => isRipActive(j));
    if (tracked.length === 0) return;
    try {
      const byId = new Map((await listMyRipJobs("all")).map((j) => [j.id, j]));
      for (const [externalId, job] of tracked) {
        const fresh = byId.get(job.id);
        if (!fresh) continue;
        rips[externalId] = fresh;
        if (fresh.status === "ready") {
          candidates = candidates.map((x) =>
            x.external_id === externalId ? { ...x, already_in_library: true } : x,
          );
        } else if (fresh.status === "failed") {
          sourceError = fresh.error_text ?? $_("sources.ingest_failed");
        }
      }
      rips = rips;
    } catch {
      // Transient; the next tick retries.
    }
    schedulePoll();
  }

  function schedulePoll() {
    if (pollTimer || !Object.values(rips).some(isRipActive)) return;
    pollTimer = setTimeout(pollRips, 3000);
  }

  async function download(c: SourceCandidate) {
    submitting[c.external_id] = true;
    sourceError = null;
    try {
      rips[c.external_id] = await submitUrl(c.webpage_url, "source_search");
      rips = rips;
      schedulePoll();
    } catch (e) {
      sourceError = e instanceof Error ? e.message : $_("sources.ingest_failed");
    } finally {
      submitting[c.external_id] = false;
    }
  }

  function ripLabel(job: RipJob): string {
    const status = $_(`url_rip.status.${job.status}`);
    return job.progress_pct > 0 ? `${status} · ${job.progress_pct}%` : `${status}…`;
  }

  onMount(async () => {
    query = page.url.searchParams.get("q") ?? "";
    mode = page.url.searchParams.get("tab") === "sources" ? "sources" : "library";
    initialized = true;
    if (query) {
      if (mode === "sources") runSourceSearch();
      else runSearch(query);
    }
    await tick();
    input?.focus();
  });

  onDestroy(() => {
    if (pollTimer) clearTimeout(pollTimer);
    if (timer) clearTimeout(timer);
  });

  let timer: ReturnType<typeof setTimeout> | null = null;
  function onInput() {
    if (mode !== "library") return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => runSearch(query), 200);
  }

  function onSubmit() {
    if (timer) clearTimeout(timer);
    if (mode === "sources") {
      syncUrl();
      runSourceSearch();
    } else {
      runSearch(query);
    }
  }

  async function runSearch(q: string) {
    syncUrl();
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

<svelte:head><title>{$_("search.title")} — SetVault</title></svelte:head>

<section class="search-body">
  <form on:submit|preventDefault={onSubmit} class="search-form" role="search">
    <input
      id="search-input"
      type="search"
      bind:this={input}
      bind:value={query}
      on:input={onInput}
      placeholder={mode === "sources" ? $_("sources.search_placeholder") : $_("search.placeholder_library")}
      aria-label={$_("search.title")}
    />
    {#if mode === "sources"}
      <button type="submit" class="btn" disabled={searching}>{$_("sources.search_submit")}</button>
    {/if}
  </form>

  <div class="tab-strip" role="tablist">
    <button
      type="button"
      role="tab"
      class="tab"
      class:active={mode === "library"}
      aria-selected={mode === "library"}
      on:click={() => setMode("library")}
    >
      {$_("sources.tab_library")}
    </button>
    <button
      type="button"
      role="tab"
      class="tab"
      class:active={mode === "sources"}
      aria-selected={mode === "sources"}
      on:click={() => setMode("sources")}
    >
      {$_("sources.tab_sources")}
    </button>
  </div>

  {#if mode === "sources"}
    {#if sourceError}<p class="admin-msg is-error" role="alert">{sourceError}</p>{/if}
    {#if erroredSources.length > 0}
      <p class="admin-msg is-warn" role="status">
        {$_("sources.partial_unavailable", {
          values: { sources: erroredSources.map(sourceLabel).join(", ") },
        })}
      </p>
    {/if}
    {#if throttledSources.length > 0}
      <p class="muted" role="status">
        {$_("search.sources_throttled", {
          values: { sources: throttledSources.map(sourceLabel).join(", ") },
        })}
      </p>
    {/if}
    {#if !searching && candidates.length === 0 && lastSourceQuery}
      <EmptyState message={$_("sources.no_results")} />
    {:else}
      <ul class="candidate-list">
        {#each candidates as c (c.external_id)}
          {@const job = rips[c.external_id]}
          <li class="candidate">
            {#if c.thumbnail_url}<img src={c.thumbnail_url} alt="" loading="lazy" />{/if}
            <div class="meta">
              <strong>{c.title}</strong>
              <span class="muted">{c.uploader ?? ""}</span>
              <span class="source-chip">{sourceLabel(c.source_kind)}</span>
              <span class="source-chip">{$_(`sources.quality.${c.expected_tier ?? "unknown"}`)}</span>
            </div>
            {#if c.already_in_library}
              <span class="badge">{$_("sources.in_library")}</span>
            {:else if job && isRipActive(job)}
              <span class="muted" role="status">{ripLabel(job)}</span>
            {:else}
              <button
                type="button"
                class="btn btn-sm"
                disabled={submitting[c.external_id]}
                on:click={() => download(c)}
              >
                {submitting[c.external_id] ? $_("sources.ingesting") : $_("sources.ingest")}
              </button>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}

  {#if mode === "library"}
    {#if !initialized}
      <p class="hint">{$_("common.loading")}</p>
    {:else if !query}
      <p class="hint">{$_("search.prompt")}</p>
    {:else if loading}
      <p class="hint">{$_("search.searching")}</p>
    {:else if !results || (results.sets.length === 0 && results.artists.length === 0)}
      <p class="hint">{$_("search.no_matches", { values: { query } })}</p>
    {:else}
      {#if results.sets.length}
        <h2 class="group">{$_("search.group_sets")}</h2>
        <ul class="result-list">
          {#each results.sets as s (s.slug)}
            <li><a href={`/sets/${s.slug}`}>{s.title}</a></li>
          {/each}
        </ul>
      {/if}
      {#if results.artists.length}
        <h2 class="group">{$_("search.group_artists")}</h2>
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
  .search-form { display: flex; gap: var(--sp-2); margin-bottom: var(--sp-3); }
  .search-form input {
    flex: 1;
    min-width: 0;
    padding: var(--sp-2) var(--sp-3);
    background: var(--bg-base);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    color: var(--text-default);
    font: inherit;
  }
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

  .candidate-list {
    list-style: none;
    padding: 0;
    margin: var(--sp-3) 0 0;
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
