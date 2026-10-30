<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { _ } from "svelte-i18n";
  import NotificationBell from "#lib/components/NotificationBell.svelte";
  import type { CurrentUser } from "#lib/api/auth.ts";

  export let user: CurrentUser;

  $: initial = (user.display_name || user.email || "?").charAt(0).toUpperCase();

  function openSearch() {
    // Already on the search page: jump to its input instead of a no-op goto.
    if (page.url.pathname === "/search") {
      document.getElementById("search-input")?.focus();
      return;
    }
    goto("/search");
  }

  function handleKey(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openSearch();
    }
  }
</script>

<svelte:window on:keydown={handleKey} />

<header class="topbar">
  <a class="brand" href="/" aria-label={$_("topbar.home")}>
    <span class="brand-dot"></span>
    <span class="brand-name">SETVAULT</span>
  </a>

  <button class="search-trigger" type="button" on:click={openSearch} aria-label={$_("topbar.open_search")}>
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
      <circle cx="7" cy="7" r="5" />
      <line x1="11" y1="11" x2="14" y2="14" />
    </svg>
    <span class="search-label">{$_("topbar.search_placeholder")}</span>
    <span class="kbd">⌘ K</span>
  </button>

  <div class="topbar-right">
    <a class="add-set" href="/sets/new">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
        <line x1="8" y1="3" x2="8" y2="13" />
        <line x1="3" y1="8" x2="13" y2="8" />
      </svg>
      <span class="add-set-label">{$_("nav.add_set")}</span>
    </a>
    <NotificationBell />
    <a class="btn btn-ghost btn-icon" href="/me/bookmarks" aria-label={$_("nav.bookmarks")}>
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
        <path d="M4 2h8v12l-4-3-4 3V2z" />
      </svg>
    </a>
    <a class="btn btn-ghost btn-icon" href="/me/downloads" aria-label={$_("nav.downloads")}>
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
        <path d="M8 1v9M4.5 6.5L8 10l3.5-3.5M2 14h12" />
      </svg>
    </a>
    <div class="user-pip" aria-label={$_("topbar.account")}>{initial}</div>
  </div>
</header>

<style>
  .user-pip {
    width: 32px;
    height: 32px;
    background: var(--accent-soft);
    border: 1px solid var(--accent);
    border-radius: 50%;
    display: grid;
    place-items: center;
    color: var(--accent);
    font-weight: 700;
    font-size: var(--ts-md);
  }
  .btn-icon {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    color: var(--text-muted);
    text-decoration: none;
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
  }
  .btn-icon:hover { color: var(--accent); border-color: var(--accent); }
  .add-set {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-1);
    height: 32px;
    padding: 0 var(--sp-3);
    color: var(--accent);
    text-decoration: none;
    border: 1px solid var(--accent);
    border-radius: var(--r-sm);
    background: var(--accent-soft);
    font-size: var(--ts-sm);
    font-weight: 600;
    white-space: nowrap;
  }
  .add-set:hover { background: var(--accent); color: var(--text-on-accent); }
  /* Without min-width: 0 the trigger can't shrink below its label's width. */
  .topbar .search-trigger { min-width: 0; }
  .search-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  @media (max-width: 760px) {
    .topbar .search-trigger .kbd { display: none; }
  }
  @media (max-width: 600px) {
    .topbar { padding: 0 var(--sp-3); gap: var(--sp-2); }
    .topbar .topbar-right { gap: var(--sp-1); }
    .topbar .search-trigger { flex: 0 0 auto; margin-left: auto; padding: 0; width: 32px; height: 32px; justify-content: center; }
    .search-label { display: none; }
    .add-set { padding: 0; width: 32px; justify-content: center; }
    .add-set-label { display: none; }
  }
</style>
