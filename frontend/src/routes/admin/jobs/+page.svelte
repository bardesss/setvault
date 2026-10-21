<script lang="ts">
  import type { PageData } from "./$types";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  export let data: PageData;
</script>

<h2>Jobs</h2>
{#if data.jobs.length === 0}
  <EmptyState message="No jobs recorded yet." />
{:else}
  <AdminTable
    columns={[
      "ID",
      "Kind",
      "Status",
      "Progress",
      "Created",
      "Finished",
      "Message",
    ]}
  >
    {#each data.jobs as j (j.id)}
      <tr>
        <td class="mono">{j.id}</td>
        <td>{j.kind}</td>
        <td>{j.status}</td>
        <td>{j.progress_pct}%</td>
        <td class="mono">{j.created_at}</td>
        <td class="mono">{j.finished_at ?? "—"}</td>
        <td>{j.message ?? ""}</td>
      </tr>
    {/each}
  </AdminTable>
{/if}
