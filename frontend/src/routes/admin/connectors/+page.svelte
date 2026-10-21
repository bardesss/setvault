<script lang="ts">
  import type { PageData } from "./$types";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  export let data: PageData;
</script>

<h2>Connectors</h2>
{#if data.connectors.length === 0}
  <EmptyState message="No connectors configured." />
{:else}
  <AdminTable columns={["Name", "Kind", "Enabled", "Scope"]}>
    {#each data.connectors as c (c.id)}
      <tr>
        <td>{c.name}</td>
        <td>{c.kind}</td>
        <td>{c.enabled ? "yes" : "no"}</td>
        <td class="mono">{JSON.stringify(c.scope_filter)}</td>
      </tr>
    {/each}
  </AdminTable>
{/if}
