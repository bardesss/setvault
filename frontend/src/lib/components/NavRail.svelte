<script lang="ts">
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { logout } from "#lib/api/auth.ts";
  import type { CurrentUser } from "#lib/api/auth.ts";

  export let user: CurrentUser;

  $: pathname = $page.url.pathname;

  function active(href: string): boolean {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(href + "/");
  }

  async function handleLogout() {
    await logout();
    goto("/login");
  }
</script>

<nav class="rail" aria-label="Primary">
  <div class="rail-section">
    <a class="rail-link" class:active={active("/")} href="/">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
        <path d="M2 7l6-5 6 5v7H2z" />
        <path d="M6 14V9h4v5" />
      </svg>
      Home
    </a>
    <a class="rail-link" class:active={active("/sets")} href="/sets">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
        <rect x="2" y="3" width="12" height="10" rx="1" />
        <path d="M2 6h12" />
      </svg>
      Library
    </a>
    <a class="rail-link" class:active={active("/search")} href="/search">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
        <circle cx="7" cy="7" r="5" />
        <line x1="11" y1="11" x2="14" y2="14" />
      </svg>
      Search
    </a>
  </div>

  <div class="rail-section">
    <div class="rail-section-title">Yours</div>
    <a class="rail-link" class:active={active("/me/bookmarks")} href="/me/bookmarks">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
        <path d="M4 2h8v12l-4-3-4 3V2z" />
      </svg>
      Bookmarks
    </a>
    <a class="rail-link" class:active={active("/me/downloads")} href="/me/downloads">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
        <path d="M8 1v9M4.5 6.5L8 10l3.5-3.5M2 14h12" />
      </svg>
      Downloads
    </a>
    <a class="rail-link" class:active={active("/settings")} href="/settings">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
        <circle cx="8" cy="8" r="2" />
        <path d="M8 1v3M8 12v3M1 8h3M12 8h3" />
      </svg>
      Settings
    </a>
  </div>

  {#if user.role === "admin"}
    <div class="rail-section">
      <div class="rail-section-title">System</div>
      <a class="rail-link" class:active={pathname.startsWith("/admin")} href="/admin/users">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" width="14" height="14" aria-hidden="true">
          <circle cx="8" cy="8" r="2" />
          <path d="M8 1v3M8 12v3M1 8h3M12 8h3" />
        </svg>
        Admin
      </a>
    </div>
  {/if}

  <div class="rail-footer">
    <div class="rail-user">{user.display_name || user.email}</div>
    <button class="rail-logout" type="button" on:click={handleLogout}>Sign out</button>
  </div>
</nav>

<style>
  .rail-footer {
    margin-top: auto;
    padding-top: var(--sp-4);
    border-top: 1px solid var(--border-subtle);
    display: grid;
    gap: var(--sp-2);
  }
  .rail-user {
    font-family: var(--font-mono);
    font-size: var(--ts-xs);
    color: var(--text-muted);
    padding: 0 var(--sp-3);
  }
  .rail-logout {
    background: transparent;
    border: 1px solid var(--border-default);
    color: var(--text-default);
    border-radius: var(--r-sm);
    padding: 6px var(--sp-3);
    cursor: pointer;
    font-family: var(--font-sans);
    font-size: var(--ts-sm);
  }
  .rail-logout:hover { border-color: var(--accent); color: var(--accent); }

  @media (max-width: 760px) {
    .rail {
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      width: 100%;
      height: 64px;
      flex-direction: row;
      padding: 0;
      border-right: none;
      border-top: 1px solid var(--border-subtle);
      z-index: 40;
    }
    .rail :global(.rail-section) { flex-direction: row; flex: 1; }
    .rail :global(.rail-section-title),
    .rail-footer { display: none; }
    .rail :global(.rail-link) {
      flex: 1;
      flex-direction: column;
      gap: 2px;
      padding: 6px;
      font-size: var(--ts-xxs);
      text-align: center;
    }
  }
</style>
