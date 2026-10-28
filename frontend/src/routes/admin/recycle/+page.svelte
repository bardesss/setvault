<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api/client.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { _, locale } from "svelte-i18n";
  import { fmtLocalDateTime } from "#lib/format.ts";

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
      error = e instanceof ApiError ? e.detail : $_("admin.common.load_failed");
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
      error = e instanceof ApiError ? e.detail : $_("admin.recycle.restore_failed");
    } finally {
      busy[slug] = false;
      busy = busy;
    }
  }

  async function purgeNow(slug: string) {
    if (!confirm($_("admin.recycle.purge_confirm", { values: { slug } }))) {
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
      error = e instanceof ApiError ? e.detail : $_("admin.recycle.purge_failed");
    } finally {
      busy[slug] = false;
      busy = busy;
    }
  }

  onMount(load);
</script>

<section class="recycle">
  <header>
    <h2>{$_("admin.recycle.title")}</h2>
    <p class="muted">{$_("admin.recycle.intro")}</p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="loading">{$_("common.loading")}</p>
  {:else if items.length === 0}
    <EmptyState message={$_("admin.recycle.empty")} />
  {:else}
    <AdminTable
      columns={[$_("admin.recycle.col_slug"), $_("admin.recycle.col_title"), $_("admin.recycle.col_deleted"), $_("admin.recycle.col_purge_after"), $_("admin.common.col_actions")]}
    >
      {#each items as item (item.id)}
        <tr>
          <td class="mono">{item.slug}</td>
          <td>{item.title}</td>
          <td class="mono">{fmtLocalDateTime(item.deleted_at, $locale)}</td>
          <td class="mono">{fmtLocalDateTime(item.purge_after_at, $locale)}</td>
          <td class="cell-actions">
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[item.slug]}
              on:click={() => restore(item.slug)}
            >{$_("admin.recycle.restore")}</button>
            <button
              type="button"
              class="btn btn-sm btn-danger"
              disabled={busy[item.slug]}
              on:click={() => purgeNow(item.slug)}
            >{$_("admin.recycle.purge_now")}</button>
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
