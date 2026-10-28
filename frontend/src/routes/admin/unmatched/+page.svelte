<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api/client.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { _, locale } from "svelte-i18n";
  import { fmtLocalDateTime } from "#lib/format.ts";
  import { codeParts } from "../codeParts.ts";

  interface UnmatchedFile {
    id: string;
    watch_folder_id: string;
    file_path: string;
    detected_at: string;
    audio_info: Record<string, unknown>;
    resolution: string;
    resolved_to_set_id: string | null;
    error_text: string | null;
  }

  interface LiveSetSummary {
    id: string;
    slug: string;
    title: string;
  }

  let items: UnmatchedFile[] = [];
  let loading = true;
  let error: string | null = null;
  let busy: Record<string, boolean> = {};
  let linkPicker: { ufId: string; slug: string } | null = null;
  let candidates: LiveSetSummary[] = [];

  async function load() {
    loading = true;
    try {
      const r = await api<{ items: UnmatchedFile[] }>("/api/admin/unmatched");
      items = r.items;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("admin.common.load_failed");
    } finally {
      loading = false;
    }
  }

  async function resolve(uf: UnmatchedFile, action: string, liveSetId?: string) {
    return resolveById(uf.id, action, liveSetId);
  }

  async function resolveById(ufId: string, action: string, liveSetId?: string) {
    busy[ufId] = true;
    busy = busy;
    try {
      await api(`/api/admin/unmatched/${ufId}/resolve`, {
        method: "POST",
        body: JSON.stringify({ action, live_set_id: liveSetId ?? null }),
      });
      items = items.filter((i) => i.id !== ufId);
      linkPicker = null;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : $_("admin.unmatched.resolve_failed");
    } finally {
      busy[ufId] = false;
      busy = busy;
    }
  }

  async function openLinkPicker(uf: UnmatchedFile) {
    linkPicker = { ufId: uf.id, slug: "" };
    try {
      const r = await api<{ items: LiveSetSummary[]; total: number }>("/api/sets?limit=200");
      candidates = r.items;
    } catch {
      candidates = [];
    }
  }

  $: filteredCandidates = candidates.filter((c) => {
    if (!linkPicker?.slug) return true;
    const q = linkPicker.slug.toLowerCase();
    return c.slug.includes(q) || c.title.toLowerCase().includes(q);
  });

  onMount(load);
</script>

<section class="unmatched">
  <header>
    <h2>{$_("admin.unmatched.title")}</h2>
    <p class="muted">
      {#each codeParts($_, "admin.unmatched.intro", { path: ".discarded/" }) as part}{#if part.code}<code>{part.text}</code>{:else}{part.text}{/if}{/each}
    </p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  {#if loading}
    <p class="loading">{$_("common.loading")}</p>
  {:else if items.length === 0}
    <EmptyState message={$_("admin.unmatched.empty")} />
  {:else}
    <AdminTable columns={[$_("admin.unmatched.col_file"), $_("admin.unmatched.col_detected"), $_("admin.unmatched.col_error"), $_("admin.common.col_actions")]}>
      {#each items as uf (uf.id)}
        <tr>
          <td class="mono ellipsis" title={uf.file_path}>{uf.file_path}</td>
          <td class="mono">{fmtLocalDateTime(uf.detected_at, $locale)}</td>
          <td class="error-cell">{uf.error_text ?? ""}</td>
          <td class="cell-actions">
            <button type="button" class="btn btn-sm" disabled={busy[uf.id]} on:click={() => openLinkPicker(uf)}>
              {$_("admin.unmatched.link")}
            </button>
            <button type="button" class="btn btn-sm" disabled={busy[uf.id]} on:click={() => resolve(uf, "create_draft")}>
              {$_("admin.unmatched.draft")}
            </button>
            <button type="button" class="btn btn-sm btn-danger" disabled={busy[uf.id]} on:click={() => resolve(uf, "discard")}>
              {$_("admin.common.discard")}
            </button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}

  {#if linkPicker}
    <aside class="picker" role="dialog" aria-label={$_("admin.unmatched.picker_label")}>
      <h3>{$_("admin.unmatched.picker_title")}</h3>
      <input
        type="text"
        placeholder={$_("admin.unmatched.picker_search")}
        bind:value={linkPicker.slug}
      />
      <ul class="candidate-list">
        {#each filteredCandidates as c (c.id)}
          <li>
            <button
              type="button"
              on:click={() => linkPicker && resolveById(linkPicker.ufId, "link_to_set", c.id)}
            >
              <strong>{c.title}</strong> <code>{c.slug}</code>
            </button>
          </li>
        {/each}
        {#if filteredCandidates.length === 0}
          <li class="empty">{$_("admin.unmatched.no_matches")}</li>
        {/if}
      </ul>
      <button type="button" class="btn btn-sm" on:click={() => { linkPicker = null; }}>{$_("common.cancel")}</button>
    </aside>
  {/if}
</section>

<style>
  .unmatched { display: grid; gap: var(--sp-3); }
  header { display: grid; gap: var(--sp-1); }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
  .loading { color: var(--text-faint); }
  .ellipsis { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .error-cell { color: var(--text-faint); font-size: var(--ts-sm); }
  .picker {
    position: fixed;
    bottom: var(--sp-4);
    right: var(--sp-4);
    width: min(420px, calc(100vw - var(--sp-8)));
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: var(--r-md);
    padding: var(--sp-3);
    box-shadow: 0 4px 16px rgba(0,0,0,0.2);
    display: grid;
    gap: var(--sp-2);
    z-index: 50;
  }
  .picker input {
    padding: var(--sp-1);
    background: var(--bg-base);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    color: inherit;
    font: inherit;
  }
  .candidate-list { list-style: none; padding: 0; margin: 0;
                    max-height: 320px; overflow-y: auto; display: grid; gap: var(--sp-1); }
  .candidate-list button {
    width: 100%;
    text-align: left;
    background: transparent;
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    padding: var(--sp-1) var(--sp-2);
    color: inherit;
    cursor: pointer;
  }
  .candidate-list button:hover { background: var(--accent-softer, transparent); }
  .candidate-list code { font-family: var(--font-mono); font-size: var(--ts-xs);
                         color: var(--text-faint); }
  .candidate-list .empty { color: var(--text-faint); font-style: italic;
                           padding: var(--sp-1) var(--sp-2); }
</style>
