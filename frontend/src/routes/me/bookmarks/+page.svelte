<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import FilterBar from "#lib/components/FilterBar.svelte";
  import { listMyBookmarks, type Bookmark } from "#lib/api/bookmarks.ts";
  import { fmtDuration } from "#lib/format.ts";

  let items: Bookmark[] = [];
  let loaded = false;
  let query = "";
  let sort: string = "recent";

  onMount(async () => {
    try {
      items = await listMyBookmarks();
    } finally {
      loaded = true;
    }
  });

  $: filtered = (() => {
    let out = items;
    if (query) {
      const q = query.toLowerCase();
      out = out.filter(
        (b) =>
          (b.live_set_title ?? "").toLowerCase().includes(q) ||
          (b.label ?? "").toLowerCase().includes(q),
      );
    }
    if (sort === "title") {
      out = out
        .slice()
        .sort((a, b) =>
          (a.live_set_title ?? "").localeCompare(b.live_set_title ?? ""),
        );
    }
    return out;
  })();

  $: bySet = filtered.reduce<Record<string, Bookmark[]>>((acc, b) => {
    const key = b.live_set_slug ?? "(unknown)";
    (acc[key] ??= []).push(b);
    return acc;
  }, {});
</script>

<svelte:head><title>{$_("bookmarks.my_title")} — SetVault</title></svelte:head>

<FilterBar
  bind:query
  bind:sort
  sortOptions={[
    { value: "recent", label: "Recently bookmarked" },
    { value: "title", label: "Set title A→Z" },
  ]}
  view="list"
/>

<section class="bookmarks-body">
  <h1 class="bookmarks-heading">{$_("bookmarks.my_title")}</h1>

  {#if !loaded}
    <p class="hint">Loading…</p>
  {:else if items.length === 0}
    <p class="hint">{$_("bookmarks.empty")}</p>
  {:else if filtered.length === 0}
    <p class="hint">No bookmarks match.</p>
  {:else}
    {#each Object.entries(bySet) as [slug, list] (slug)}
      <article>
        <h2><a href="/sets/{slug}">{list[0].live_set_title ?? slug}</a></h2>
        <ul>
          {#each list as b (b.id)}
            <li>
              <a
                href={`/sets/${slug}${b.position_seconds !== null ? `?t=${b.position_seconds}` : ""}`}
              >
                {b.position_seconds === null
                  ? $_("bookmarks.entire_set")
                  : fmtDuration(b.position_seconds)}
              </a>
              {#if b.label}<span class="label">{b.label}</span>{/if}
            </li>
          {/each}
        </ul>
      </article>
    {/each}
  {/if}
</section>

<style>
  .bookmarks-body {
    padding: var(--sp-4) var(--sp-8) var(--sp-8);
    display: grid;
    gap: var(--sp-4);
    max-width: 900px;
    margin: 0 auto;
  }
  .bookmarks-heading {
    font-size: var(--ts-2xl);
    letter-spacing: var(--ls-tight);
    color: var(--text-strong);
    margin: 0;
  }
  .hint {
    padding: var(--sp-8);
    text-align: center;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: var(--ts-md);
  }
  article {
    display: grid;
    gap: var(--sp-2);
    padding: var(--sp-4);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
  }
  article h2 { margin: 0; font-size: var(--ts-lg); }
  article h2 a { color: var(--text-strong); text-decoration: none; }
  article h2 a:hover { color: var(--accent); }
  ul { list-style: none; padding: 0; margin: 0; display: grid; gap: var(--sp-1); }
  ul li a {
    font-family: var(--font-mono);
    font-size: var(--ts-sm);
    color: var(--accent);
    text-decoration: none;
  }
  .label { color: var(--text-muted); font-style: italic; margin-left: var(--sp-2); }
</style>
