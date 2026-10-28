<script lang="ts">
  import { onMount } from "svelte";
  import { _, locale } from "svelte-i18n";
  import type { PageData } from "./$types";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import StatusBlock from "#lib/components/StatusBlock.svelte";
  import {
    backupUrl,
    deleteBackup,
    listBackups,
    runBackup,
    type BackupList,
  } from "#lib/api/backups.ts";
  import {
    getSettings,
    updateSettings,
    type AdminSettings,
  } from "#lib/api/settings.ts";
  import { toast } from "#lib/stores/toast.ts";
  import { fmtBytes, fmtLocalDateTime } from "#lib/format.ts";

  export let data: PageData;

  let backups: BackupList = data.backups;
  let settings: AdminSettings | null = null;
  let dirText = "";
  let busy = false;
  let formError: string | null = null;
  let pendingDelete: string | null = null;

  function fmtWhen(iso: string | null): string {
    return iso ? fmtLocalDateTime(iso, $locale) : "–";
  }

  function errText(e: unknown): string {
    return e instanceof Error ? e.message : $_("admin.common.failed");
  }

  function adopt(s: AdminSettings) {
    settings = s;
    dirText = s.backup_dir ?? "";
  }

  async function refresh() {
    try {
      backups = await listBackups();
    } catch (e) {
      toast.error(errText(e));
    }
  }

  onMount(async () => {
    try {
      adopt(await getSettings());
    } catch (e) {
      formError = errText(e);
    }
  });

  async function save() {
    if (!settings) return;
    busy = true;
    formError = null;
    try {
      adopt(
        await updateSettings({
          backup_enabled: settings.backup_enabled,
          backup_time: settings.backup_time,
          backup_keep: settings.backup_keep,
          backup_dir: dirText.trim() === "" ? null : dirText.trim(),
        }),
      );
      toast.success($_("admin.backups.saved"));
      await refresh();
    } catch (e) {
      formError = errText(e);
    } finally {
      busy = false;
    }
  }

  async function runNow() {
    busy = true;
    try {
      await runBackup();
      toast.success($_("admin.backups.started"));
      // The worker needs a moment; pick up the new file and status.
      setTimeout(() => void refresh(), 4000);
    } catch (e) {
      toast.error(errText(e));
    } finally {
      busy = false;
    }
  }

  async function confirmDelete() {
    const name = pendingDelete;
    pendingDelete = null;
    if (!name) return;
    try {
      await deleteBackup(name);
      toast.success($_("admin.backups.deleted"));
      await refresh();
    } catch (e) {
      toast.error(errText(e));
    }
  }

  $: last = backups.last;
  $: failed = last.status === "failed";
</script>

<h2>{$_("admin.backups.title")}</h2>

<StatusBlock>
  <p
    class="status"
    class:is-failed={failed}
    data-testid="backup-status"
    role={failed ? "alert" : "status"}
  >
    {#if !last.at}
      {$_("admin.backups.never")}
    {:else if failed}
      {$_("admin.backups.status_failed", {
        values: { when: fmtWhen(last.at), error: last.error ?? "" },
      })}
    {:else}
      {$_("admin.backups.status_ok", {
        values: { when: fmtWhen(last.at), size: fmtBytes(last.bytes, $locale) },
      })}
    {/if}
  </p>
  {#if !backups.dir_persistent}
    <p class="warn" role="alert" data-testid="backup-not-persistent">
      {$_("admin.backups.not_persistent", { values: { dir: backups.dir } })}
    </p>
  {/if}
</StatusBlock>

<StatusBlock title={$_("admin.backups.settings_title")}>
  {#if formError}
    <p class="admin-msg is-error" role="alert">{formError}</p>
  {/if}
  {#if settings}
    <div class="settings-form">
      <label class="settings-row">
        <input type="checkbox" bind:checked={settings.backup_enabled} />
        {$_("admin.backups.enabled")}
      </label>
      <label class="settings-row">
        {$_("admin.backups.time", { values: { tz: backups.tz } })}
        <input type="time" bind:value={settings.backup_time} />
      </label>
      <p class="hint" data-testid="backup-tz">
        {$_("admin.backups.tz", { values: { tz: backups.tz } })}
      </p>
      <label class="settings-row">
        {$_("admin.backups.keep")}
        <input
          type="number"
          min="1"
          max="365"
          class="num-input"
          bind:value={settings.backup_keep}
        />
        {$_("admin.backups.keep_suffix")}
      </label>
      <label class="settings-col">
        {$_("admin.backups.dir")}
        <input
          type="text"
          class="mono"
          placeholder={backups.dir}
          bind:value={dirText}
        />
      </label>
      <p class="hint">
        {$_("admin.backups.dir_hint", { values: { dir: backups.dir } })}
      </p>
      <div>
        <button
          type="button"
          class="btn btn-primary btn-sm"
          disabled={busy}
          on:click={save}
        >
          {$_("admin.backups.save")}
        </button>
      </div>
    </div>
  {/if}
</StatusBlock>

<StatusBlock title={$_("admin.backups.files_title")}>
  <div>
    <button type="button" class="btn btn-primary btn-sm" disabled={busy} on:click={runNow}>
      {$_("admin.backups.run_now")}
    </button>
  </div>
  {#if backups.dir_error}
    <p class="warn" role="alert" data-testid="backup-dir-error">
      {$_("admin.backups.dir_unreadable", {
        values: { dir: backups.dir, error: backups.dir_error },
      })}
    </p>
  {:else if backups.files.length === 0}
    <p class="hint" data-testid="backup-empty">{$_("admin.backups.empty")}</p>
  {:else}
    <AdminTable
      columns={[
        $_("admin.backups.col_name"),
        $_("admin.backups.col_date"),
        $_("admin.backups.col_size"),
        $_("admin.backups.col_actions"),
      ]}
    >
      {#each backups.files as f (f.name)}
        <tr data-testid="backup-file">
          <td class="mono">{f.name}</td>
          <td>{fmtWhen(f.created_at)}</td>
          <td>{fmtBytes(f.bytes, $locale)}</td>
          <td class="actions">
            <a class="btn btn-sm" href={backupUrl(f.name)} download>
              {$_("admin.backups.download")}
            </a>
            <button
              type="button"
              class="btn btn-sm btn-danger"
              on:click={() => (pendingDelete = f.name)}
            >
              {$_("admin.backups.delete")}
            </button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</StatusBlock>

<StatusBlock>
  <p class="hint">{$_("admin.backups.full_export_hint")}</p>
  <a class="btn" href="/api/admin/backup" download>{$_("admin.backups.full_export")}</a>
</StatusBlock>

<ConfirmDialog
  open={pendingDelete !== null}
  title={$_("admin.backups.delete_title")}
  message={$_("admin.backups.delete_message", { values: { name: pendingDelete ?? "" } })}
  confirmLabel={$_("admin.backups.delete")}
  danger
  on:confirm={confirmDelete}
  on:cancel={() => (pendingDelete = null)}
/>

<style>
  .hint { color: var(--text-faint); margin: 0; font-size: var(--ts-sm); }
  .status { margin: 0; font-weight: 600; }
  .status.is-failed { color: var(--accent-error); }
  .warn { margin: 0; color: var(--accent-error); }
  .settings-form { display: grid; gap: var(--sp-3); }
  .settings-row { display: flex; align-items: center; gap: var(--sp-2); }
  .settings-col { display: grid; gap: var(--sp-1); }
  .num-input { width: 6rem; }
  .actions { display: flex; gap: var(--sp-2); }
</style>
