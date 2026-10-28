<script lang="ts">
  import { _, locale } from "svelte-i18n";
  import type { PageData } from "./$types";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import MediaRootForm from "#lib/components/MediaRootForm.svelte";
  import Modal from "#lib/components/Modal.svelte";
  import { errorMessage } from "#lib/api/errors.ts";
  import { fmtBytes } from "#lib/format.ts";
  import {
    deleteMediaRoot,
    listMediaRoots,
    probeMediaRoot,
    reapplyTemplate,
    type MediaRoot,
  } from "#lib/api/media_roots.ts";
  import { toast } from "#lib/stores/toast.ts";

  export let data: PageData;

  let roots: MediaRoot[] = data.roots;
  let formOpen = false;
  let editing: MediaRoot | null = null;
  let pendingReapply: MediaRoot | null = null;
  let pendingDelete: MediaRoot | null = null;
  let busyId: string | null = null;

  // Only "ok" reads as healthy; every other status draws the eye.
  const HEALTH_CLASS: Record<string, string> = {
    ok: "badge-resolved",
    near_full: "badge-raw",
    readonly: "badge-raw",
    unreachable: "badge-bad",
    unknown: "badge-neutral",
  };

  async function refresh() {
    try {
      roots = await listMediaRoots();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  function openAdd() {
    editing = null;
    formOpen = true;
  }

  function openEdit(r: MediaRoot) {
    editing = r;
    formOpen = true;
  }

  async function onSaved() {
    formOpen = false;
    toast.success($_("admin.storage.saved"));
    await refresh();
  }

  async function checkNow(r: MediaRoot) {
    busyId = r.id;
    try {
      const updated = await probeMediaRoot(r.id);
      roots = roots.map((x) => (x.id === updated.id ? updated : x));
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      busyId = null;
    }
  }

  async function confirmReapply() {
    const r = pendingReapply;
    pendingReapply = null;
    if (!r) return;
    try {
      await reapplyTemplate(r.id);
      toast.success($_("admin.storage.reapply_queued"));
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  async function confirmDelete() {
    const r = pendingDelete;
    pendingDelete = null;
    if (!r) return;
    try {
      await deleteMediaRoot(r.id);
      toast.success($_("admin.storage.deleted"));
      await refresh();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }
</script>

<div class="head">
  <h2>{$_("admin.storage.title")}</h2>
  <button type="button" class="btn btn-primary btn-sm" on:click={openAdd}>
    {$_("admin.storage.add")}
  </button>
</div>

{#if roots.length === 0}
  <EmptyState message={$_("admin.storage.empty")} />
{:else}
  <AdminTable
    columns={[
      $_("admin.storage.col_name"),
      $_("admin.storage.col_path"),
      $_("admin.storage.col_default"),
      $_("admin.storage.col_quota"),
      $_("admin.storage.col_sets"),
      $_("admin.storage.col_health"),
      $_("admin.storage.col_actions"),
    ]}
  >
    {#each roots as r (r.id)}
      <tr class:is-disabled={!r.enabled} data-testid="root-row" data-root-name={r.name}>
        <td>{r.name}</td>
        <td class="mono">{r.host_path}</td>
        <td>{r.default_for_ingest ? $_("common.yes") : $_("common.no")}</td>
        <td>{r.max_bytes === null ? $_("admin.storage.unlimited") : fmtBytes(r.max_bytes, $locale)}</td>
        <td>{r.set_count}</td>
        <td>
          <span
            class="badge {HEALTH_CLASS[r.last_health_status ?? 'unknown']}"
            data-testid="root-health"
            data-status={r.last_health_status ?? "unknown"}
          >
            {$_(`admin.storage.health.${r.last_health_status ?? "unknown"}`)}
          </span>
        </td>
        <td class="cell-actions">
          <button type="button" class="btn btn-sm" on:click={() => openEdit(r)}>
            {$_("admin.storage.edit")}
          </button>
          <button
            type="button"
            class="btn btn-sm"
            disabled={busyId === r.id}
            on:click={() => checkNow(r)}
          >
            {$_("admin.storage.check_now")}
          </button>
          <button
            type="button"
            class="btn btn-sm"
            disabled={!r.naming_template}
            title={r.naming_template ? "" : $_("admin.storage.reapply_no_template")}
            on:click={() => (pendingReapply = r)}
          >
            {$_("admin.storage.reapply")}
          </button>
          <button type="button" class="btn btn-sm btn-danger" on:click={() => (pendingDelete = r)}>
            {$_("admin.storage.delete")}
          </button>
        </td>
      </tr>
    {/each}
  </AdminTable>
{/if}

<Modal
  open={formOpen}
  title={editing ? $_("admin.storage.edit_title") : $_("admin.storage.add_title")}
  on:close={() => (formOpen = false)}
>
  {#key `${formOpen}:${editing?.id ?? "new"}`}
    {#if formOpen}
      <MediaRootForm root={editing} on:saved={onSaved} />
    {/if}
  {/key}
</Modal>

<ConfirmDialog
  open={pendingReapply !== null}
  title={$_("admin.storage.reapply_title")}
  message={$_("admin.storage.reapply_message", {
    values: { count: pendingReapply?.set_count ?? 0, name: pendingReapply?.name ?? "" },
  })}
  confirmLabel={$_("admin.storage.reapply")}
  on:confirm={confirmReapply}
  on:cancel={() => (pendingReapply = null)}
/>

<ConfirmDialog
  open={pendingDelete !== null}
  title={$_("admin.storage.delete_title")}
  message={$_("admin.storage.delete_message", { values: { name: pendingDelete?.name ?? "" } })}
  confirmLabel={$_("admin.storage.delete")}
  danger
  on:confirm={confirmDelete}
  on:cancel={() => (pendingDelete = null)}
/>

<style>
  .badge-bad {
    color: var(--accent-error);
    border-color: var(--accent-error);
    background: var(--bg-elevated);
  }
  .head { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); }
  .head h2 { margin: 0; }
</style>
