<script lang="ts">
  import { _ } from "svelte-i18n";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { goto } from "$app/navigation";
  import TabStrip from "#lib/components/TabStrip.svelte";
  import { dismissDiscovery, ripDiscovery, type Discovery } from "#lib/api/monitors.ts";
  import type { PageData } from "./$types";

  export let data: PageData;
  let rows: Discovery[] = data.discoveries;
  let errorMsg: string | null = null;
  $: rows = data.discoveries;

  let active = data.status;
  $: active = data.status;
  $: tabs = [
    { id: "pending_review", label: $_("discoveries.tab_pending"), count: data.pendingCount },
    { id: "ingested", label: $_("discoveries.tab_ingested") },
    { id: "dismissed", label: $_("discoveries.tab_dismissed") },
    { id: "all", label: $_("discoveries.tab_all") },
  ];
  $: if (active !== data.status) {
    void goto(`?status=${active}`);
  }

  async function rip(d: Discovery) {
    try {
      await ripDiscovery(d.id);
      rows = rows.map((x) => (x.id === d.id ? { ...x, status: "ingested" } : x));
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : "failed";
    }
  }
  async function dismiss(d: Discovery) {
    try {
      await dismissDiscovery(d.id);
      rows = rows.map((x) => (x.id === d.id ? { ...x, status: "dismissed" } : x));
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : "failed";
    }
  }
</script>

<svelte:head><title>{$_("discoveries.title")} - SetVault</title></svelte:head>

<section>
  <h1>{$_("discoveries.title")}</h1>
  <TabStrip {tabs} bind:active />
  {#if errorMsg}<p class="admin-msg is-error" role="alert">{errorMsg}</p>{/if}
  {#if rows.length === 0}
    <EmptyState message={$_("discoveries.empty")} />
  {:else}
    <AdminTable
      columns={[
        $_("discoveries.col_title"),
        $_("discoveries.col_source"),
        $_("discoveries.col_confidence"),
        $_("discoveries.col_status"),
        "",
      ]}
    >
      {#each rows as d (d.id)}
        <tr>
          <td><a href={d.webpage_url} target="_blank" rel="noreferrer">{d.title}</a></td>
          <td class="mono">{d.source_kind}</td>
          <td class="mono">{d.confidence}</td>
          <td class="mono">{$_(`discoveries.status_${d.status}`)}</td>
          <td class="cell-actions">
            {#if d.status === "pending_review"}
              <button type="button" class="btn btn-sm" on:click={() => rip(d)}>{$_("discoveries.rip")}</button>
              <button type="button" class="btn btn-sm" on:click={() => dismiss(d)}>{$_("discoveries.dismiss")}</button>
            {/if}
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<style>
  section { display: grid; gap: var(--sp-4); }
</style>
