<script lang="ts">
  import { _ } from "svelte-i18n";
  import type { PageData } from "./$types";
  import type { JobRow } from "./+page";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  export let data: PageData;

  const KNOWN_STATUSES = ["queued", "started", "finished", "failed"];
  let open: Record<string, boolean> = {};

  function toggle(id: string) {
    open[id] = !open[id];
    open = open;
  }

  function when(iso: string | null): string {
    return iso ? new Date(iso).toLocaleString() : "—";
  }

  function duration(j: JobRow): string {
    if (!j.started_at || !j.finished_at) return "—";
    const ms = Date.parse(j.finished_at) - Date.parse(j.started_at);
    if (!Number.isFinite(ms) || ms < 0) return "—";
    const s = ms / 1000;
    if (s < 60) return `${s.toFixed(1)} s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} min ${Math.round(s % 60)} s`;
    return `${Math.floor(m / 60)} h ${m % 60} min`;
  }

  function statusLabel(status: string): string {
    return KNOWN_STATUSES.includes(status)
      ? $_(`admin.jobs.status.${status}`)
      : status;
  }

  function hasResult(j: JobRow): boolean {
    return !!j.result && Object.keys(j.result).length > 0;
  }
</script>

<h2>{$_("admin.jobs.title")}</h2>
{#if data.jobs.length === 0}
  <EmptyState message={$_("admin.jobs.empty")} />
{:else}
  <AdminTable
    caption={$_("admin.jobs.title")}
    columns={[
      $_("admin.jobs.col_kind"),
      $_("admin.jobs.col_status"),
      $_("admin.jobs.col_started"),
      $_("admin.jobs.col_finished"),
      $_("admin.jobs.col_duration"),
    ]}
  >
    {#each data.jobs as j (j.id)}
      <tr class:is-open={open[j.id]}>
        <td>
          <button
            type="button"
            class="job-toggle"
            aria-expanded={!!open[j.id]}
            aria-controls={`job-detail-${j.id}`}
            on:click={() => toggle(j.id)}
          >
            <span class="chev" aria-hidden="true">{open[j.id] ? "▾" : "▸"}</span>
            <span class="mono">{j.kind}</span>
          </button>
        </td>
        <td>
          <span class="badge job-status job-status-{j.status}">{statusLabel(j.status)}</span>
        </td>
        <td class="mono">{when(j.started_at)}</td>
        <td class="mono">{when(j.finished_at)}</td>
        <td class="mono">{duration(j)}</td>
      </tr>
      {#if open[j.id]}
        <tr class="job-detail" id={`job-detail-${j.id}`}>
          <td colspan="5">
            <dl>
              <dt>{$_("admin.jobs.rq_id")}</dt>
              <dd class="mono">{j.rq_id}</dd>
              <dt>{$_("admin.jobs.message")}</dt>
              <dd class="mono pre">{j.message ?? "—"}</dd>
              <dt>{$_("admin.jobs.result")}</dt>
              <dd>
                {#if hasResult(j)}
                  <pre class="mono">{JSON.stringify(j.result, null, 2)}</pre>
                {:else}
                  <span class="mono">—</span>
                {/if}
              </dd>
            </dl>
          </td>
        </tr>
      {/if}
    {/each}
  </AdminTable>
{/if}

<style>
  .job-toggle {
    display: inline-flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 0;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    cursor: pointer;
    text-align: left;
  }
  .job-toggle:focus-visible {
    outline: 2px solid var(--border-focus);
    outline-offset: 2px;
  }
  .chev { color: var(--text-faint); width: 1ch; }
  .job-status {
    color: var(--text-muted);
    border-color: var(--border-default);
    background: var(--bg-elevated);
  }
  .job-status-finished {
    color: var(--accent-success);
    border-color: var(--accent-soft);
    background: var(--accent-softer);
  }
  .job-status-failed {
    color: var(--accent-error);
    border-color: var(--accent-error);
  }
  .job-detail td { background: var(--bg-elevated); }
  dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: var(--sp-1) var(--sp-3);
    margin: 0;
  }
  dt { color: var(--text-faint); font-size: var(--ts-sm); }
  dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
  .pre { white-space: pre-wrap; }
  pre {
    margin: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
</style>
