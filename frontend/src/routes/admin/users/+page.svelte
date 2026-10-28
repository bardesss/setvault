<script lang="ts">
  import type { PageData } from "./$types";
  import { _ } from "svelte-i18n";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  export let data: PageData;
</script>

<h2>{$_("admin.users.title")}</h2>
{#if data.users.length === 0}
  <EmptyState message={$_("admin.users.empty")} />
{:else}
  <AdminTable
    columns={[$_("admin.users.col_email"), $_("admin.users.col_username"), $_("admin.users.col_display_name"), $_("admin.users.col_role"), $_("admin.users.col_status")]}
  >
    {#each data.users as u (u.id)}
      <tr>
        <td>{u.email}</td>
        <td>{u.username}</td>
        <td>{u.display_name}</td>
        <td>{u.role}</td>
        <td>{u.disabled_at ? $_("admin.users.status_disabled") : $_("admin.users.status_active")}</td>
      </tr>
    {/each}
  </AdminTable>
{/if}
