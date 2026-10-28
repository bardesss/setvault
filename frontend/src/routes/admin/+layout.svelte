<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { toStore } from "svelte/store";
  import { api, ApiError } from "#lib/api/client.ts";
  import { session } from "#lib/stores/session.ts";
  import { codeParts } from "./codeParts.ts";

  $: if ($session && $session.role !== "admin") {
    void goto("/");
  }

  $: tabs = [
    { href: "/admin/users", label: $_("admin.layout.tab_users") },
    { href: "/admin/connectors", label: $_("admin.layout.tab_connectors") },
    { href: "/admin/email", label: $_("admin.layout.tab_email") },
    { href: "/admin/providers", label: $_("admin.layout.tab_providers") },
    { href: "/admin/sources", label: $_("admin.layout.tab_sources") },
    { href: "/admin/monitors", label: $_("admin.layout.tab_monitors") },
    { href: "/admin/storage", label: $_("admin.layout.tab_storage") },
    { href: "/admin/watch-folders", label: $_("admin.layout.tab_watch_folders") },
    { href: "/admin/unmatched", label: $_("admin.layout.tab_unmatched") },
    { href: "/admin/drafts", label: $_("admin.layout.tab_drafts") },
    { href: "/admin/duplicates", label: $_("admin.layout.tab_duplicates") },
    { href: "/admin/quality", label: $_("admin.layout.tab_quality") },
    { href: "/admin/wanted", label: $_("admin.layout.tab_wanted") },
    { href: "/admin/catalog", label: $_("admin.layout.tab_catalog") },
    { href: "/admin/recycle", label: $_("admin.layout.tab_recycle") },
    { href: "/admin/jobs", label: $_("admin.layout.tab_jobs") },
    { href: "/admin/tasks", label: $_("admin.layout.tab_tasks") },
    { href: "/admin/webhooks", label: $_("admin.layout.tab_webhooks") },
    { href: "/admin/backups", label: $_("admin.layout.tab_backups") },
    { href: "/admin/health", label: $_("admin.layout.tab_health") },
    { href: "/admin/system", label: $_("admin.layout.tab_system") },
  ];

  // Legacy `$:` statements don't track rune state like `page`; a store does.
  const pageUrl = toStore(() => page.url);
  $: currentPath = $pageUrl.pathname;

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

<svelte:head><title>{$_("admin.layout.title")} - SetVault</title></svelte:head>

<section class="admin">
  {#if bannerVersion}
    {@const v = bannerVersion}
    <aside class="admin-banner" role="status">
      <strong>{$_("admin.layout.update_available")}</strong>
      {#each codeParts($_, "admin.layout.running_version", { current: v.current, latest: v.latest_known ?? "" }) as part}{#if part.code}<code>{part.text}</code>{:else}{part.text}{/if}{/each}
      {#if v.latest_release_url}
        <a href={v.latest_release_url} target="_blank" rel="noopener">{$_("admin.layout.release_notes")}</a>
      {/if}
      <button type="button" class="btn btn-sm snooze" on:click={dismiss}>{$_("admin.layout.snooze")}</button>
    </aside>
  {/if}

  <header class="admin-header">
    <h1>{$_("admin.layout.title")}</h1>
    <nav class="tabs" aria-label={$_("admin.layout.sections")}>
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
