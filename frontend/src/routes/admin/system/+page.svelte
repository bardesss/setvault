<script lang="ts">
  import { onMount } from "svelte";
  import { _ } from "svelte-i18n";
  import type { PageData } from "./$types";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import StatusBlock from "#lib/components/StatusBlock.svelte";
  import {
    getSettings,
    updateSettings,
    type AdminSettings,
  } from "#lib/api/settings.ts";
  import { codeParts } from "../codeParts.ts";
  export let data: PageData;

  $: envEntries = Object.entries(data.info.env).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  let settings: AdminSettings | null = null;
  let settingsBusy = false;
  let settingsError: string | null = null;

  onMount(async () => {
    try {
      settings = await getSettings();
    } catch (e) {
      settingsError = e instanceof Error ? e.message : $_("admin.common.failed");
    }
  });

  async function saveSettings() {
    if (!settings) return;
    settingsBusy = true;
    settingsError = null;
    try {
      settings = await updateSettings({
        monitors_allow_all_users: settings.monitors_allow_all_users,
        monitor_interval_seconds: settings.monitor_interval_seconds,
      });
    } catch (e) {
      settingsError = e instanceof Error ? e.message : $_("admin.common.failed");
    } finally {
      settingsBusy = false;
    }
  }

  // Auto-login is only meaningful (and only accepted by the API) when this is
  // the sole account — hide the toggle otherwise.
  $: singleUser = data.info.user_count === 1;

  async function saveAutoLogin() {
    if (!settings) return;
    settingsBusy = true;
    settingsError = null;
    try {
      settings = await updateSettings({
        single_user_auto_login: settings.single_user_auto_login,
      });
    } catch (e) {
      settingsError = e instanceof Error ? e.message : $_("admin.common.failed");
      if (settings) settings.single_user_auto_login = !settings.single_user_auto_login;
    } finally {
      settingsBusy = false;
    }
  }
</script>

<h2>{$_("admin.system.title")}</h2>

<StatusBlock
  title={$_("admin.system.build")}
  rows={[
    { label: $_("admin.system.version"), value: String(data.info.version) },
    { label: $_("admin.system.users"), value: String(data.info.user_count) },
    { label: $_("admin.system.sets"), value: String(data.info.set_count) },
  ]}
/>

<StatusBlock title={$_("admin.system.monitoring")}>
  {#if settingsError}
    <p class="admin-msg is-error" role="alert">{settingsError}</p>
  {/if}
  {#if settings}
    <div class="settings-form">
      <label class="settings-row">
        <input
          type="checkbox"
          bind:checked={settings.monitors_allow_all_users}
        />
        {$_("settings.monitors_allow_all_users")}
      </label>
      <label class="settings-row">
        {$_("settings.monitor_interval_seconds")}
        <input
          type="number"
          min="60"
          class="num-input"
          bind:value={settings.monitor_interval_seconds}
        />
      </label>
      <div>
        <button
          type="button"
          class="btn btn-primary btn-sm"
          disabled={settingsBusy}
          on:click={saveSettings}
        >
          {$_("settings.save")}
        </button>
      </div>
    </div>
  {/if}
</StatusBlock>

{#if singleUser && settings}
  <StatusBlock title={$_("settings.access_title")}>
    <label class="settings-row">
      <input
        type="checkbox"
        bind:checked={settings.single_user_auto_login}
        disabled={settingsBusy}
        on:change={saveAutoLogin}
      />
      {$_("settings.single_user_auto_login")}
    </label>
    <p class="hint">{$_("settings.single_user_auto_login_warning")}</p>
  </StatusBlock>
{/if}

<StatusBlock title={$_("admin.system.backup")}>
  <p class="hint">
    {#each codeParts($_, "admin.system.backup_hint", { tar: ".tar", pg_dump: "pg_dump" }) as part}{#if part.code}<code>{part.text}</code>{:else}{part.text}{/if}{/each}
    {$_("admin.backups.system_link")}
  </p>
  <a class="btn btn-primary" href="/api/admin/backup" download>{$_("admin.system.download_backup")}</a>
  <a class="btn" href="/admin/backups">{$_("admin.backups.title")}</a>
</StatusBlock>

<StatusBlock title={$_("admin.system.environment")}>
  <p class="hint">
    {#each codeParts($_, "admin.system.redacted_hint", { a: "_KEY", b: "_SECRET", c: "_TOKEN", d: "_PASSWORD", e: "_HOOK_SECRET" }) as part}{#if part.code}<code>{part.text}</code>{:else}{part.text}{/if}{/each}
  </p>
  <AdminTable columns={[$_("admin.system.col_name"), $_("admin.system.col_value")]}>
    {#each envEntries as [k, v] (k)}
      <tr>
        <td class="mono">{k}</td>
        <td class="mono val">{v}</td>
      </tr>
    {/each}
  </AdminTable>
</StatusBlock>

<style>
  .hint { color: var(--text-faint); margin: 0; font-size: var(--ts-sm); }
  .val { word-break: break-all; }
  .settings-form { display: grid; gap: var(--sp-3); }
  .settings-row { display: flex; align-items: center; gap: var(--sp-2); }
  .num-input { width: 8rem; }
</style>
