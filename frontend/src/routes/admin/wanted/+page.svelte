<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "$lib/api/client";
  import AdminTable from "$lib/components/AdminTable.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import { fmtLocalDateTime, wantedResult, type WantedEvent } from "$lib/wanted";

  interface WantedItem {
    id: string;
    slug: string;
    title: string;
    quality_label: string;
    quality_tier: string | null;
    last_upgrade_search_at: string | null;
    last_event: WantedEvent | null;
  }

  let items: WantedItem[] = [];
  let loading = true;
  let error: string | null = null;
  let busy: Record<string, boolean> = {};
  let status: Record<string, string> = {};

  async function load() {
    loading = true;
    error = null;
    try {
      const r = await api<{ items: WantedItem[] }>("/api/admin/wanted?limit=100");
      items = r.items;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "Could not load wanted sets.";
    } finally {
      loading = false;
    }
  }

  async function searchNow(slug: string) {
    busy[slug] = true;
    busy = busy;
    error = null;
    try {
      const r = await api<{ status: "queued" | "already_queued" }>(
        `/api/admin/wanted/${encodeURIComponent(slug)}/search`,
        { method: "POST" },
      );
      status[slug] = r.status === "queued" ? "Queued" : "Already queued";
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "Search failed.";
    } finally {
      busy[slug] = false;
      busy = busy;
      status = status;
    }
  }

  onMount(load);
</script>

<section class="wanted">
  <header>
    <h2>Wanted</h2>
    <p class="muted">Sets below the quality cutoff, least recently searched first. Search now looks for a better copy right away.</p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if items.length === 0}
    <EmptyState message="Every set meets the quality cutoff." />
  {:else}
    <AdminTable
      columns={[
        "Set",
        "Quality",
        "Last searched",
        "Last result",
        "Actions",
      ]}
    >
      {#each items as item (item.id)}
        <tr>
          <td><a href={`/sets/${encodeURIComponent(item.slug)}`}>{item.title}</a></td>
          <td>{item.quality_label}</td>
          <td class="mono">{item.last_upgrade_search_at ? fmtLocalDateTime(item.last_upgrade_search_at) : "Never"}</td>
          <td>{wantedResult(item.last_event, item.last_upgrade_search_at)}</td>
          <td class="cell-actions">
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[item.slug]}
              on:click={() => searchNow(item.slug)}
            >Search now</button>
            {#if status[item.slug]}<span class="muted" role="status">{status[item.slug]}</span>{/if}
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<style>
  .wanted { display: grid; gap: var(--sp-3); }
  header { display: grid; gap: var(--sp-1); }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
</style>
