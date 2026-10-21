<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api/client.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";

  interface RecycledSet {
    id: string;
    slug: string;
    title: string;
    deleted_at: string | null;
    purge_after_at: string | null;
    audio_path: string;
    duration_seconds: number | null;
  }

  let items: RecycledSet[] = [];
  let loading = true;
  let error: string | null = null;
  let busy: Record<string, boolean> = {};

  async function load() {
    loading = true;
    error = null;
    try {
      const r = await api<{ items: RecycledSet[] }>("/api/admin/recycle");
      items = r.items;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "load failed";
    } finally {
      loading = false;
    }
  }

  async function restore(slug: string) {
    busy[slug] = true;
    busy = busy;
    try {
      await api(`/api/admin/recycle/${encodeURIComponent(slug)}/restore`, {
        method: "POST",
      });
      items = items.filter((i) => i.slug !== slug);
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "restore failed";
    } finally {
      busy[slug] = false;
      busy = busy;
    }
  }

  async function purgeNow(slug: string) {
    if (!confirm(`Hard-delete "${slug}" permanently? This cannot be undone.`)) {
      return;
    }
    busy[slug] = true;
    busy = busy;
    try {
      await api(`/api/admin/recycle/${encodeURIComponent(slug)}/purge-now`, {
        method: "POST",
      });
      items = items.filter((i) => i.slug !== slug);
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "purge failed";
    } finally {
      busy[slug] = false;
      busy = busy;
    }
  }

  function fmtDate(iso: string | null): string {
    if (!iso) return "";
    return iso.slice(0, 16).replace("T", " ");
  }

  onMount(load);
</script>

<section class="recycle">
  <header>
    <h2>Recycle bin</h2>
    <p class="muted">
      Soft-deleted sets are kept here until their grace window expires, then
      the scheduled purge job removes them. Restore them or purge them now.
    </p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="loading">Loading…</p>
  {:else if items.length === 0}
    <EmptyState message="Nothing in the recycle bin." />
  {:else}
    <AdminTable
      columns={["Slug", "Title", "Deleted", "Auto-purge after", "Actions"]}
    >
      {#each items as item (item.id)}
        <tr>
          <td class="mono">{item.slug}</td>
          <td>{item.title}</td>
          <td class="mono">{fmtDate(item.deleted_at)}</td>
          <td class="mono">{fmtDate(item.purge_after_at)}</td>
          <td class="cell-actions">
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[item.slug]}
              on:click={() => restore(item.slug)}
            >Restore</button>
            <button
              type="button"
              class="btn btn-sm btn-danger"
              disabled={busy[item.slug]}
              on:click={() => purgeNow(item.slug)}
            >Purge now</button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<style>
  .recycle { display: grid; gap: var(--sp-3); }
  header { display: grid; gap: var(--sp-1); }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
  .loading { color: var(--text-faint); }
</style>
