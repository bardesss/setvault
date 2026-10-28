<script lang="ts">
  import { onMount } from "svelte";
  import { _, locale } from "svelte-i18n";
  import { fmtDuration, fmtLocalDateTime } from "#lib/format.ts";
  import { api, ApiError } from "#lib/api/client.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";

  interface OriginalSet {
    slug: string;
    title: string;
    status: string;
    duration_seconds: number | null;
    /** e.g. "FLAC (Bandcamp)", as on the set page. */
    quality_label?: string;
  }

  interface HeldDuplicate {
    id: string;
    slug: string;
    title: string;
    source_type: string;
    duration_seconds: number | null;
    created_at: string | null;
    status?: string;
    /** "matched by backfill": a published set the library cleanup left unmerged. */
    reason?: string | null;
    quality_label?: string;
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
      error = e instanceof ApiError ? e.detail : $_("admin.common.load_failed");
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
      error = e instanceof ApiError
        ? e.detail
        : $_(action === "keep" ? "admin.duplicates.keep_failed" : "admin.common.discard_failed");
    } finally {
      busy[slug] = false;
      busy = busy;
    }
  }


  onMount(load);
</script>

<section class="duplicates">
  <header>
    <h2>{$_("admin.duplicates.title")}</h2>
    <p class="muted">{$_("admin.duplicates.intro")}</p>
    <p class="muted">{$_("admin.duplicates.intro_backfill")}</p>
    <p class="muted" data-testid="dup-discard-note">{$_("admin.duplicates.discard_note")}</p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="loading">{$_("common.loading")}</p>
  {:else if items.length === 0}
    <EmptyState message={$_("admin.duplicates.empty")} />
  {:else}
    <AdminTable
      columns={[$_("admin.duplicates.col_arrival"), $_("admin.common.col_source"), $_("admin.common.col_length"), $_("admin.common.col_arrived"), $_("admin.duplicates.col_duplicate_of"), $_("admin.common.col_actions")]}
    >
      {#each items as item (item.id)}
        <tr>
          <td>
            {item.title}
            {#if item.reason === "matched by backfill"}
              <span class="muted note" data-testid="dup-reason">{$_("admin.duplicates.matched_by_backfill")}</span>
            {/if}
            {#if item.quality_label}
              <span class="muted note" data-testid="dup-quality">{item.quality_label}</span>
            {/if}
          </td>
          <td class="mono">{item.source_type}</td>
          <td class="mono">{item.duration_seconds == null ? "" : fmtDuration(item.duration_seconds)}</td>
          <td class="mono">{fmtLocalDateTime(item.created_at, $locale)}</td>
          <td>
            {#if item.original}
              <a href={`/sets/${encodeURIComponent(item.original.slug)}`}>{item.original.title}</a>
              <span class="mono muted">{item.original.duration_seconds == null ? "" : fmtDuration(item.original.duration_seconds)}</span>
              {#if item.original.quality_label}
                <span class="muted note" data-testid="dup-original-quality">{item.original.quality_label}</span>
              {/if}
            {:else}
              <span class="muted">{$_("admin.duplicates.original_removed")}</span>
            {/if}
          </td>
          <td class="cell-actions">
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[item.slug]}
              on:click={() => resolve(item.slug, "keep")}
            >{item.status === "published" ? $_("admin.duplicates.keep") : $_("admin.duplicates.keep_publish")}</button>
            <button
              type="button"
              class="btn btn-sm btn-danger"
              disabled={busy[item.slug]}
              on:click={() => resolve(item.slug, "discard")}
            >{$_("admin.common.discard")}</button>
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
  .note { display: block; }
</style>
