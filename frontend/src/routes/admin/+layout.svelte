<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { api, ApiError } from "$lib/api/client";
  import { session } from "$lib/stores/session";

  $: if ($session && $session.role !== "admin") {
    void goto("/");
  }

  const tabs = [
    { href: "/admin/users", label: "Users" },
    { href: "/admin/connectors", label: "Connectors" },
    { href: "/admin/providers", label: "Providers" },
    { href: "/admin/sources", label: "Sources" },
    { href: "/admin/monitors", label: "Monitors" },
    { href: "/admin/storage", label: "Storage" },
    { href: "/admin/watch-folders", label: "Watch folders" },
    { href: "/admin/unmatched", label: "Unmatched" },
    { href: "/admin/duplicates", label: "Duplicates" },
    { href: "/admin/quality", label: "Quality" },
    { href: "/admin/wanted", label: "Wanted" },
    { href: "/admin/catalog", label: "Catalog" },
    { href: "/admin/recycle", label: "Recycle" },
    { href: "/admin/jobs", label: "Jobs" },
    { href: "/admin/tasks", label: "Tasks" },
    { href: "/admin/webhooks", label: "Webhooks" },
    { href: "/admin/health", label: "Health" },
    { href: "/admin/system", label: "System" },
  ];

  $: currentPath = $page.url.pathname;

  // New-version banner (§J16). Snooze persists in LocalStorage for 24h.
  interface HealthVersion {
    current: string;
    latest_known: string | null;
    latest_release_url: string | null;
    is_outdated: boolean;
  }

  let bannerVersion: HealthVersion | null = null;
  const SNOOZE_KEY = "setvault.adminVersionSnoozeUntil";

  function snoozeActive(): boolean {
    if (typeof localStorage === "undefined") return false;
    const raw = localStorage.getItem(SNOOZE_KEY);
    if (!raw) return false;
    const until = Number(raw);
    return Number.isFinite(until) && until > Date.now();
  }

  function dismiss() {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(
        SNOOZE_KEY,
        String(Date.now() + 24 * 60 * 60 * 1000),
      );
    }
    bannerVersion = null;
  }

  async function loadVersion() {
    if (snoozeActive()) return;
    try {
      const data = await api<{ version: HealthVersion }>("/api/admin/health");
      if (data.version.is_outdated) {
        bannerVersion = data.version;
      }
    } catch (e) {
      // Quiet: a network error here just means no banner this load.
      if (!(e instanceof ApiError)) return;
    }
  }

  onMount(loadVersion);
</script>

<svelte:head><title>Admin - SetVault</title></svelte:head>

<section class="admin">
  {#if bannerVersion}
    {@const v = bannerVersion}
    <aside class="admin-banner" role="status">
      <strong>Update available.</strong>
      You're running <code>{v.current}</code>; latest is
      <code>{v.latest_known}</code>.
      {#if v.latest_release_url}
        <a href={v.latest_release_url} target="_blank" rel="noopener">Release notes →</a>
      {/if}
      <button type="button" class="btn btn-sm snooze" on:click={dismiss}>Snooze 24h</button>
    </aside>
  {/if}

  <header class="admin-header">
    <h1>Admin</h1>
    <nav class="tabs" aria-label="Admin sections">
      {#each tabs as t (t.href)}
        <a
          href={t.href}
          class:active={currentPath === t.href || currentPath.startsWith(t.href + "/")}
        >
          {t.label}
        </a>
      {/each}
    </nav>
  </header>
  <div class="content"><slot /></div>
</section>

<style>
  .admin {
    padding: var(--sp-6);
    display: grid;
    gap: var(--sp-4);
  }
  .admin-banner .snooze { margin-left: auto; }
  .admin-header { display: grid; gap: var(--sp-3); }
  .tabs {
    display: flex;
    gap: var(--sp-1);
    border-bottom: 1px solid var(--border-default);
    flex-wrap: wrap;
  }
  .tabs a {
    padding: var(--sp-2) var(--sp-3);
    border-bottom: 2px solid transparent;
    color: var(--text-faint);
    text-decoration: none;
    font-weight: 600;
  }
  .tabs a:hover { color: inherit; }
  .tabs a.active {
    color: inherit;
    border-bottom-color: var(--accent);
  }
  .content { display: grid; gap: var(--sp-3); }
</style>
