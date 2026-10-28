<script lang="ts">
  import type { PageData } from "./$types";
  import { _ } from "svelte-i18n";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  export let data: PageData;
</script>

<h2>{$_("admin.connectors.title")}</h2>
{#if data.connectors.length === 0}
  <EmptyState message={$_("admin.connectors.empty")} />
{:else}
  <AdminTable columns={[$_("admin.connectors.col_name"), $_("admin.connectors.col_kind"), $_("admin.connectors.col_enabled"), $_("admin.connectors.col_scope")]}>
    {#each data.connectors as c (c.id)}
      <tr>
        <td>{c.name}</td>
        <td>{c.kind}</td>
        <td>{c.enabled ? $_("admin.common.yes") : $_("admin.common.no")}</td>
        <td class="mono">{JSON.stringify(c.scope_filter)}</td>
      </tr>
    {/each}
  </AdminTable>
{/if}
