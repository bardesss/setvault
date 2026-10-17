<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "$lib/api/client";
  import AdminTable from "$lib/components/AdminTable.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";

  interface OriginalSet {
    slug: string;
    title: string;
    status: string;
    duration_seconds: number | null;
  }

  interface HeldDuplicate {
    id: string;
    slug: string;
    title: string;
    source_type: string;
    duration_seconds: number | null;
    created_at: string | null;
    original: OriginalSet | null;
  }

  let items: HeldDuplicate[] = [];
  let loading = true;
  let error: string | null = null;
  let busy: Record<string, boolean> = {};

  async function load() {
    loading = true;
    error = null;
    try {
      const r = await api<{ items: HeldDuplicate[] }>("/api/admin/duplicates");
      items = r.items;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "load failed";
    } finally {
      loading = false;
    }
  }

  async function resolve(slug: string, action: "keep" | "discard") {
    busy[slug] = true;
    busy = busy;
    try {
      await api(`/api/admin/duplicates/${encodeURIComponent(slug)}/${action}`, {
        method: "POST",
      });
      items = items.filter((i) => i.slug !== slug);
    } catch (e) {
      error = e instanceof ApiError ? e.detail : `${action} failed`;
    } finally {
      busy[slug] = false;
      busy = busy;
    }
  }

  function fmtDuration(s: number | null): string {
    if (s == null) return "";
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
  }

  function fmtDate(iso: string | null): string {
    if (!iso) return "";
    return iso.slice(0, 16).replace("T", " ");
  }

  onMount(load);
</script>

<section class="duplicates">
  <header>
    <h2>Duplicates</h2>
    <p class="muted">
      New arrivals whose audio fingerprint matches a set you already have are
      held here as drafts instead of being published. Keep one to publish it
      anyway, or discard it to the recycle bin.
    </p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="loading">Loading…</p>
  {:else if items.length === 0}
    <EmptyState message="No duplicates waiting for review." />
  {:else}
    <AdminTable
      columns={["Arrival", "Source", "Length", "Arrived", "Duplicate of", "Actions"]}
    >
      {#each items as item (item.id)}
        <tr>
          <td>{item.title}</td>
          <td class="mono">{item.source_type}</td>
          <td class="mono">{fmtDuration(item.duration_seconds)}</td>
          <td class="mono">{fmtDate(item.created_at)}</td>
          <td>
            {#if item.original}
              <a href={`/sets/${encodeURIComponent(item.original.slug)}`}>{item.original.title}</a>
              <span class="mono muted">{fmtDuration(item.original.duration_seconds)}</span>
            {:else}
              <span class="muted">(original removed)</span>
            {/if}
          </td>
          <td class="cell-actions">
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[item.slug]}
              on:click={() => resolve(item.slug, "keep")}
            >Keep &amp; publish</button>
            <button
              type="button"
              class="btn btn-sm btn-danger"
              disabled={busy[item.slug]}
              on:click={() => resolve(item.slug, "discard")}
            >Discard</button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<style>
  .duplicates { display: grid; gap: var(--sp-3); }
  header { display: grid; gap: var(--sp-1); }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
  .loading { color: var(--text-faint); }
</style>
