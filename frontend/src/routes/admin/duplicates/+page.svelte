<script lang="ts">
  import { onMount } from "svelte";
  import { locale } from "svelte-i18n";
  import { fmtLocalDateTime } from "$lib/wanted";
  import { api, ApiError } from "$lib/api/client";
  import AdminTable from "$lib/components/AdminTable.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";

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
    <p class="muted">
      The quality backfill's duplicate cleanup also lists published sets here
      that are the same audio as an older set but weren't merged automatically
      (for example: upgrades are off, the copies belong to different owners, or
      there isn't enough information to compare them). They stay published:
      Keep removes them from this list, Discard merges their comments,
      bookmarks and history into the original and moves them to the recycle
      bin.
    </p>
    <p class="muted" data-testid="dup-discard-note">
      Discard always keeps the original's audio, even when the listed copy has
      better quality. Each row shows both copies' quality so you can compare.
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
          <td>
            {item.title}
            {#if item.reason === "matched by backfill"}
              <span class="muted note" data-testid="dup-reason">Published · matched by backfill</span>
            {/if}
            {#if item.quality_label}
              <span class="muted note" data-testid="dup-quality">{item.quality_label}</span>
            {/if}
          </td>
          <td class="mono">{item.source_type}</td>
          <td class="mono">{fmtDuration(item.duration_seconds)}</td>
          <td class="mono">{fmtLocalDateTime(item.created_at, $locale)}</td>
          <td>
            {#if item.original}
              <a href={`/sets/${encodeURIComponent(item.original.slug)}`}>{item.original.title}</a>
              <span class="mono muted">{fmtDuration(item.original.duration_seconds)}</span>
              {#if item.original.quality_label}
                <span class="muted note" data-testid="dup-original-quality">{item.original.quality_label}</span>
              {/if}
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
            >{item.status === "published" ? "Keep" : "Keep & publish"}</button>
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
  .note { display: block; }
</style>
