<script lang="ts">
  import { refreshAll, goto } from "$app/navigation";
  import { _ } from "svelte-i18n";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { mergeEntities, deleteEntity, unmergeEntity } from "#lib/api/catalog_admin.ts";
  import type { EntityKind } from "#lib/api/catalog.ts";
  import type { PageData } from "./$types";

  export let data: PageData;

  const KINDS: EntityKind[] = ["artists", "venues", "parties", "series"];
  const KIND_KEYS: Record<EntityKind, string> = {
    artists: "admin.catalog.kind_artists",
    venues: "admin.catalog.kind_venues",
    parties: "admin.catalog.kind_parties",
    series: "admin.catalog.kind_series",
  };
  let busy = false;
  let error: string | null = null;

  function switchKind(k: EntityKind) {
    goto(`/admin/catalog?kind=${k}`);
  }

  async function mergeCluster(cluster: { id: string; name: string }[]) {
    const survivor = cluster[0];
    if (!confirm($_("catalog.confirm_merge", { values: { name: survivor.name } }))) return;
    busy = true;
    error = null;
    try {
      for (const loser of cluster.slice(1)) {
        await mergeEntities(data.kind, loser.id, survivor.id);
      }
      await refreshAll();
    } catch (e) {
      error = e instanceof Error ? e.message : $_("admin.common.failed");
    } finally {
      busy = false;
    }
  }

  async function del(slug: string) {
    if (!confirm($_("catalog.confirm_delete"))) return;
    busy = true;
    error = null;
    try {
      await deleteEntity(data.kind, slug);
      await refreshAll();
    } catch (e) {
      error = e instanceof Error ? e.message : $_("admin.common.failed");
    } finally {
      busy = false;
    }
  }

  async function unmerge(loserId: string) {
    if (!confirm($_("catalog.confirm_unmerge"))) return;
    busy = true;
    error = null;
    try {
      await unmergeEntity(data.kind, loserId);
      await refreshAll();
    } catch (e) {
      error = e instanceof Error ? e.message : $_("admin.common.failed");
    } finally {
      busy = false;
    }
  }
</script>

<svelte:head><title>{$_("catalog.admin_title")} - SetVault</title></svelte:head>

<section class="catalog-admin">
  <h2>{$_("catalog.admin_title")}</h2>

  <nav class="kind-switch" aria-label={$_("admin.catalog.kind_label")}>
    {#each KINDS as k}
      <button
        type="button"
        class:active={k === data.kind}
        on:click={() => switchKind(k)}
      >{$_(KIND_KEYS[k])}</button>
    {/each}
  </nav>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  <h3>{$_("catalog.possible_duplicates")}</h3>
  {#if data.clusters.length === 0}
    <EmptyState message={$_("catalog.no_duplicates")} />
  {:else}
    {#each data.clusters as cluster}
      <div class="cluster">
        <span>{cluster.map((e) => e.name).join("  ·  ")}</span>
        <button
          type="button"
          class="btn btn-primary btn-sm"
          disabled={busy}
          on:click={() => mergeCluster(cluster)}
        >
          {$_("catalog.merge_into_first")}
        </button>
      </div>
    {/each}
  {/if}

  <h3>{$_("catalog.merged_title")}</h3>
  {#if data.merged.length === 0}
    <EmptyState message={$_("catalog.no_merged")} />
  {:else}
    {#each data.merged as m (m.id)}
      <div class="cluster">
        <span>{m.name} → {m.survivor_name ?? "?"}</span>
        <button class="btn btn-ghost btn-sm" type="button" disabled={busy} on:click={() => unmerge(m.id)}>
          {$_("catalog.unmerge")}
        </button>
      </div>
    {/each}
  {/if}

  <h3>{$_("catalog.all_of_kind")}</h3>
  {#if data.items.length === 0}
    <EmptyState message={$_("catalog.none")} />
  {:else}
    <AdminTable columns={[$_("catalog.name"), $_("admin.catalog.col_slug"), $_("catalog.sets"), ""]}>
      {#each data.items as e (e.id)}
        <tr>
          <td>{e.name}</td>
          <td class="mono">{e.slug}</td>
          <td>{e.ref_count}</td>
          <td>
            {#if e.ref_count === 0}
              <button
                type="button"
                class="btn btn-ghost btn-sm"
                disabled={busy}
                on:click={() => del(e.slug)}
              >
                {$_("catalog.delete")}
              </button>
            {/if}
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<style>
  .catalog-admin { display: grid; gap: var(--sp-4); }
  .kind-switch { display: flex; gap: var(--sp-1); flex-wrap: wrap; }
  .kind-switch button {
    padding: var(--sp-1) var(--sp-2);
    background: transparent;
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    color: var(--text-faint);
    cursor: pointer;
    font: inherit;
  }
  .kind-switch button:hover { color: inherit; }
  .kind-switch button.active {
    font-weight: 700;
    color: inherit;
    border-color: var(--accent);
  }
  .cluster {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: var(--sp-2);
    border: 1px solid var(--border-subtle);
    border-radius: var(--r-sm);
    margin-bottom: var(--sp-1);
  }
</style>
