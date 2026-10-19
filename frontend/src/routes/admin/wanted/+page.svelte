<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import { api, ApiError } from "$lib/api/client";
  import AdminTable from "$lib/components/AdminTable.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";

  interface WantedItem {
    id: string;
    slug: string;
    title: string;
    quality_label: string;
    quality_tier: string | null;
    last_upgrade_search_at: string | null;
    last_event: { outcome: string; reason: string | null; created_at: string } | null;
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
      error = e instanceof ApiError ? e.detail : $_("wanted.load_failed");
    } finally {
      loading = false;
    }
  }

  async function searchNow(slug: string) {
    busy[slug] = true;
    busy = busy;
    try {
      const r = await api<{ status: "queued" | "already_queued" }>(
        `/api/admin/wanted/${encodeURIComponent(slug)}/search`,
        { method: "POST" },
      );
      status[slug] = r.status === "queued" ? $_("wanted.queued") : $_("wanted.already_queued");
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("wanted.search_failed");
    } finally {
      busy[slug] = false;
      busy = busy;
      status = status;
    }
  }

  function fmtDate(iso: string | null): string {
    if (!iso) return "";
    return iso.slice(0, 16).replace("T", " ");
  }

  function fmtResult(ev: WantedItem["last_event"]): string {
    if (!ev) return $_("wanted.none");
    return ev.reason ? `${ev.outcome}: ${ev.reason}` : ev.outcome;
  }

  onMount(load);
</script>

<section class="wanted">
  <header>
    <h2>{$_("wanted.heading")}</h2>
    <p class="muted">{$_("wanted.intro")}</p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if items.length === 0}
    <EmptyState message={$_("wanted.empty")} />
  {:else}
    <AdminTable
      columns={[
        $_("wanted.col_set"),
        $_("wanted.col_quality"),
        $_("wanted.col_searched"),
        $_("wanted.col_result"),
        $_("wanted.col_actions"),
      ]}
    >
      {#each items as item (item.id)}
        <tr>
          <td><a href={`/sets/${encodeURIComponent(item.slug)}`}>{item.title}</a></td>
          <td>{item.quality_label}</td>
          <td class="mono">{item.last_upgrade_search_at ? fmtDate(item.last_upgrade_search_at) : $_("wanted.never")}</td>
          <td>{fmtResult(item.last_event)}</td>
          <td class="cell-actions">
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[item.slug]}
              on:click={() => searchNow(item.slug)}
            >{$_("wanted.search_now")}</button>
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
