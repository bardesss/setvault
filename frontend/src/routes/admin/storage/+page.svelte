<script lang="ts">
  import type { PageData } from "./$types";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  export let data: PageData;

  function formatBytes(n: number | null): string {
    if (n === null) return "unlimited";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = n;
    let i = 0;
    while (value >= 1024 && i < units.length - 1) {
      value /= 1024;
      i += 1;
    }
    return `${value.toFixed(1)} ${units[i]}`;
  }
</script>

<h2>Storage</h2>
{#if data.roots.length === 0}
  <EmptyState message="No media roots configured." />
{:else}
  <AdminTable
    columns={["Name", "Host path", "Default ingest", "Quota", "Health"]}
  >
    {#each data.roots as r (r.id)}
      <tr>
        <td>{r.name}</td>
        <td class="mono">{r.host_path}</td>
        <td>{r.default_for_ingest ? "yes" : "no"}</td>
        <td>{formatBytes(r.max_bytes)}</td>
        <td>{r.last_health_status ?? "unknown"}</td>
      </tr>
    {/each}
  </AdminTable>
{/if}
