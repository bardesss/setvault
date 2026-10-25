<script lang="ts">
  import { onMount } from "svelte";
  import { locale } from "svelte-i18n";
  import { fmtLocalDateTime } from "#lib/wanted.ts";
  import { formatTime } from "#lib/stores/audio.ts";
  import { api, ApiError } from "#lib/api/client.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";

  interface Draft {
    id: string;
    slug: string;
    title: string;
    source_type: string;
    duration_seconds: number | null;
    created_at: string | null;
    /** Has a playable stream, so it can be published. */
    ready: boolean;
    /** Its rip is still running: leave it alone. */
    processing: boolean;
    rip_status: string | null;
    error: string | null;
    duplicate_of: { slug: string; title: string } | null;
  }

  let items: Draft[] = [];
  let loading = true;
  let error: string | null = null;
  let busy: Record<string, boolean> = {};
  let confirming: Draft | null = null;

  async function load() {
    loading = true;
    error = null;
    try {
      items = (await api<{ items: Draft[] }>("/api/admin/drafts")).items;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "load failed";
    } finally {
      loading = false;
    }
  }

  async function act(slug: string, action: "publish" | "discard") {
    busy[slug] = true;
    busy = busy;
    error = null;
    try {
      await api(`/api/admin/drafts/${encodeURIComponent(slug)}/${action}`, { method: "POST" });
      items = items.filter((i) => i.slug !== slug);
    } catch (e) {
      error = e instanceof ApiError ? e.detail : `${action} failed`;
    } finally {
      busy[slug] = false;
      busy = busy;
    }
  }

  function state(d: Draft): string {
    if (d.processing) return `Processing (${d.rip_status})`;
    if (d.duplicate_of) return "Held as a duplicate";
    if (d.ready) return "Ready to publish";
    if (d.rip_status === "failed") return "Rip failed";
    return "Not finished: no playable stream";
  }

  onMount(load);
</script>

<section class="drafts">
  <header>
    <h2>Drafts</h2>
    <p class="muted">
      Sets that never reached Library: still being processed, held as a
      duplicate, or left unfinished by a failed rip or processing step.
      Publish one that has a playable stream, or discard it to the recycle
      bin (purged after 14 days).
    </p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="loading">Loading…</p>
  {:else if items.length === 0}
    <EmptyState message="No drafts. Everything you have is in Library." />
  {:else}
    <AdminTable columns={["Set", "Source", "Length", "Arrived", "State", "Actions"]}>
      {#each items as item (item.id)}
        <tr data-testid="draft-row">
          <td>
            <a href={`/sets/${encodeURIComponent(item.slug)}`}>{item.title}</a>
            {#if item.duplicate_of}
              <span class="muted note">
                Duplicate of
                <a href={`/sets/${encodeURIComponent(item.duplicate_of.slug)}`}>{item.duplicate_of.title}</a>
              </span>
            {/if}
          </td>
          <td class="mono">{item.source_type}</td>
          <td class="mono">{item.duration_seconds == null ? "" : formatTime(item.duration_seconds)}</td>
          <td class="mono">{fmtLocalDateTime(item.created_at, $locale)}</td>
          <td>
            <span data-testid="draft-state">{state(item)}</span>
            {#if item.error}<span class="muted note" data-testid="draft-error">{item.error}</span>{/if}
          </td>
          <td class="cell-actions">
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[item.slug] || !item.ready || item.processing}
              title={item.ready ? undefined : "No playable stream yet"}
              on:click={() => act(item.slug, "publish")}
            >Publish</button>
            <button
              type="button"
              class="btn btn-sm btn-danger"
              disabled={busy[item.slug] || item.processing}
              on:click={() => (confirming = item)}
            >Discard</button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<ConfirmDialog
  open={confirming !== null}
  title="Discard draft?"
  message={confirming ? `“${confirming.title}” moves to the recycle bin and is purged after 14 days.` : ""}
  confirmLabel="Discard"
  danger
  on:confirm={() => { const d = confirming; confirming = null; if (d) void act(d.slug, "discard"); }}
  on:cancel={() => (confirming = null)}
/>

<style>
  .drafts { display: grid; gap: var(--sp-3); }
  header { display: grid; gap: var(--sp-1); }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
  .loading { color: var(--text-faint); }
  .note { display: block; }
</style>
