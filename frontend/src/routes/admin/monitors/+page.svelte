<script lang="ts">
  import { _ } from "svelte-i18n";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import {
    createMonitor,
    deleteMonitor,
    setMonitorEnabled,
    type Monitor,
  } from "#lib/api/monitors.ts";
  import type { PageData } from "./$types";

  export let data: PageData;
  let monitors: Monitor[] = data.monitors;
  let queryText = "";
  let sourceKind = "";
  let errorMsg: string | null = null;
  let busy = false;

  async function add() {
    if (!queryText.trim()) return;
    busy = true;
    errorMsg = null;
    try {
      const m = await createMonitor({
        kind: "query",
        query_text: queryText.trim(),
        source_kind: sourceKind.trim() || null,
      });
      monitors = [m, ...monitors];
      queryText = "";
      sourceKind = "";
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : "failed";
    } finally {
      busy = false;
    }
  }

  async function toggle(m: Monitor) {
    errorMsg = null;
    try {
      const updated = await setMonitorEnabled(m.id, !m.enabled);
      monitors = monitors.map((x) => (x.id === updated.id ? updated : x));
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : "failed";
    }
  }

  async function remove(m: Monitor) {
    errorMsg = null;
    try {
      await deleteMonitor(m.id);
      monitors = monitors.filter((x) => x.id !== m.id);
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : "failed";
    }
  }
</script>

<svelte:head><title>{$_("monitors.admin_title")} - SetVault</title></svelte:head>

<section>
  <h1>{$_("monitors.admin_title")}</h1>

  {#if errorMsg}
    <p class="admin-msg is-error" role="alert">{errorMsg}</p>
  {/if}

  <form class="add" on:submit|preventDefault={add}>
    <input
      type="text"
      bind:value={queryText}
      placeholder={$_("monitors.query_placeholder")}
      aria-label={$_("monitors.query_placeholder")}
    />
    <input
      type="text"
      bind:value={sourceKind}
      placeholder={$_("monitors.source_optional")}
      aria-label={$_("monitors.source_optional")}
    />
    <button class="btn" type="submit" disabled={busy}>{$_("monitors.add")}</button>
  </form>

  {#if monitors.length === 0}
    <EmptyState message={$_("monitors.empty")} />
  {:else}
    <AdminTable
      columns={[
        $_("monitors.col_query"),
        $_("monitors.col_source"),
        $_("monitors.col_last_checked"),
        $_("monitors.col_enabled"),
        "",
      ]}
    >
      {#each monitors as m (m.id)}
        <tr class:is-disabled={!m.enabled}>
          <td>{m.query_text ?? m.external_id}</td>
          <td class="mono">{m.source_kind ?? $_("monitors.all_sources")}</td>
          <td class="mono">{m.last_checked_at ?? "—"}</td>
          <td>{m.enabled ? "✓" : "—"}</td>
          <td class="cell-actions">
            <button type="button" class="btn btn-sm" on:click={() => toggle(m)}>
              {m.enabled ? $_("monitors.disable") : $_("monitors.enable")}
            </button>
            <button type="button" class="btn btn-sm" on:click={() => remove(m)}>
              {$_("monitors.delete")}
            </button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<style>
  section { display: grid; gap: var(--sp-4); }
  .add { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
  .add input { flex: 1 1 200px; }
</style>
