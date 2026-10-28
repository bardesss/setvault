<script lang="ts">
  import { onMount } from "svelte";
  import { _, locale } from "svelte-i18n";
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
      error = e instanceof ApiError ? e.detail : $_("admin.common.load_failed");
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
      error = e instanceof ApiError
        ? e.detail
        : $_(action === "publish" ? "admin.drafts.publish_failed" : "admin.common.discard_failed");
    } finally {
      busy[slug] = false;
      busy = busy;
    }
  }

  function state(d: Draft, t: typeof $_): string {
    if (d.processing) return t("admin.drafts.state_processing", { values: { status: String(d.rip_status) } });
    if (d.duplicate_of) return t("admin.drafts.state_duplicate");
    if (d.ready) return t("admin.drafts.state_ready");
    if (d.rip_status === "failed") return t("admin.drafts.state_rip_failed");
    return t("admin.drafts.state_unfinished");
  }

  onMount(load);
</script>

<section class="drafts">
  <header>
    <h2>{$_("admin.drafts.title")}</h2>
    <p class="muted">{$_("admin.drafts.intro")}</p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="loading">{$_("common.loading")}</p>
  {:else if items.length === 0}
    <EmptyState message={$_("admin.drafts.empty")} />
  {:else}
    <AdminTable columns={[$_("admin.drafts.col_set"), $_("admin.common.col_source"), $_("admin.common.col_length"), $_("admin.common.col_arrived"), $_("admin.drafts.col_state"), $_("admin.common.col_actions")]}>
      {#each items as item (item.id)}
        <tr data-testid="draft-row">
          <td>
            <a href={`/sets/${encodeURIComponent(item.slug)}`}>{item.title}</a>
            {#if item.duplicate_of}
              <span class="muted note">
                {$_("admin.drafts.duplicate_of")}
                <a href={`/sets/${encodeURIComponent(item.duplicate_of.slug)}`}>{item.duplicate_of.title}</a>
              </span>
            {/if}
          </td>
          <td class="mono">{item.source_type}</td>
          <td class="mono">{item.duration_seconds == null ? "" : formatTime(item.duration_seconds)}</td>
          <td class="mono">{fmtLocalDateTime(item.created_at, $locale)}</td>
          <td>
            <span data-testid="draft-state">{state(item, $_)}</span>
            {#if item.error}<span class="muted note" data-testid="draft-error">{item.error}</span>{/if}
          </td>
          <td class="cell-actions">
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[item.slug] || !item.ready || item.processing}
              title={item.ready ? undefined : $_("admin.drafts.no_stream_yet")}
              on:click={() => act(item.slug, "publish")}
            >{$_("admin.drafts.publish")}</button>
            <button
              type="button"
              class="btn btn-sm btn-danger"
              disabled={busy[item.slug] || item.processing}
              on:click={() => (confirming = item)}
            >{$_("admin.common.discard")}</button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<ConfirmDialog
  open={confirming !== null}
  title={$_("admin.drafts.discard_title")}
  message={confirming ? $_("admin.drafts.discard_message", { values: { title: confirming.title } }) : ""}
  confirmLabel={$_("admin.common.discard")}
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
