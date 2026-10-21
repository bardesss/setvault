<script lang="ts">
  import type { PageData } from "./$types";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  export let data: PageData;
</script>

<h2>Users</h2>
{#if data.users.length === 0}
  <EmptyState message="No users." />
{:else}
  <AdminTable
    columns={["Email", "Username", "Display name", "Role", "Status"]}
  >
    {#each data.users as u (u.id)}
      <tr>
        <td>{u.email}</td>
        <td>{u.username}</td>
        <td>{u.display_name}</td>
        <td>{u.role}</td>
        <td>{u.disabled_at ? "disabled" : "active"}</td>
      </tr>
    {/each}
  </AdminTable>
{/if}
