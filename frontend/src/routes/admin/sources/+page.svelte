<script lang="ts">
  import { _ } from "svelte-i18n";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import YtdlpCookiesAdmin from "#lib/components/YtdlpCookiesAdmin.svelte";
  import {
    setSourceEnabled,
    setSourceRateLimit,
    type SourceState,
  } from "#lib/api/ingest_sources.ts";
  import type { PageData } from "./$types";

  export let data: PageData;
  let sources: SourceState[] = data.sources;
  let busy: Record<string, boolean> = {};
  let errorMsg: string | null = null;

  let draft: Record<string, { max: number; window: number }> = {};
  function seed(list: SourceState[]) {
    const next: Record<string, { max: number; window: number }> = {};
    for (const s of list) {
      next[s.kind] = {
        max: s.rate_limit_max,
        window: s.rate_limit_window_seconds,
      };
    }
    draft = next;
  }
  seed(sources);

  async function toggle(s: SourceState) {
    busy[s.kind] = true;
    busy = busy;
    errorMsg = null;
    try {
      const updated = await setSourceEnabled(s.kind, !s.enabled);
      apply(updated);
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : $_("admin.common.failed");
    } finally {
      busy[s.kind] = false;
      busy = busy;
    }
  }

  async function saveRateLimit(s: SourceState) {
    busy[s.kind] = true;
    busy = busy;
    errorMsg = null;
    try {
      const d = draft[s.kind];
      const updated = await setSourceRateLimit(
        s.kind,
        d.max,
        d.window,
      );
      apply(updated);
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : $_("admin.common.failed");
    } finally {
      busy[s.kind] = false;
      busy = busy;
    }
  }

  function apply(updated: SourceState) {
    sources = sources.map((x) => (x.kind === updated.kind ? updated : x));
    draft[updated.kind] = {
      max: updated.rate_limit_max,
      window: updated.rate_limit_window_seconds,
    };
    draft = draft;
  }
</script>

<svelte:head><title>{$_("sources.admin_title")} - SetVault</title></svelte:head>

<section>
  <h1>{$_("sources.admin_title")}</h1>

  {#if errorMsg}
    <p class="admin-msg is-error" role="alert">{errorMsg}</p>
  {/if}

  {#if sources.length === 0}
    <EmptyState message={$_("sources.admin_empty")} />
  {:else}
    <AdminTable
      columns={[
        $_("sources.col_source"),
        $_("sources.col_state"),
        $_("sources.col_enabled"),
        $_("sources.col_rate_max"),
        $_("sources.col_rate_window"),
        "",
      ]}
    >
      {#each sources as s (s.kind)}
        <tr class:is-disabled={!s.enabled}>
          <td>{s.name}</td>
          <td class="mono">{s.state}{s.last_error ? ` — ${s.last_error}` : ""}</td>
          <td>{s.enabled ? "✓" : "—"}</td>
          <td>
            <input
              type="number"
              min="1"
              class="rate-input"
              bind:value={draft[s.kind].max}
            />
          </td>
          <td>
            <input
              type="number"
              min="1"
              class="rate-input"
              bind:value={draft[s.kind].window}
            />
          </td>
          <td class="cell-actions">
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[s.kind]}
              on:click={() => saveRateLimit(s)}
            >
              {$_("sources.save")}
            </button>
            <button
              type="button"
              class="btn btn-sm"
              disabled={busy[s.kind]}
              on:click={() => toggle(s)}
            >
              {s.enabled ? $_("sources.disable") : $_("sources.enable")}
            </button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}

  <YtdlpCookiesAdmin />
</section>

<style>
  section { display: grid; gap: var(--sp-4); }
  .rate-input { width: 6rem; }
</style>
