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
      settingsError = e instanceof Error ? e.message : "failed";
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
      settingsError = e instanceof Error ? e.message : "failed";
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
      settingsError = e instanceof Error ? e.message : "failed";
      if (settings) settings.single_user_auto_login = !settings.single_user_auto_login;
    } finally {
      settingsBusy = false;
    }
  }
</script>

<h2>System</h2>

<StatusBlock
  title="Build"
  rows={[
    { label: "Version", value: String(data.info.version) },
    { label: "Users", value: String(data.info.user_count) },
    { label: "Sets", value: String(data.info.set_count) },
  ]}
/>

<StatusBlock title="Monitoring">
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

<StatusBlock title="Backup">
  <p class="hint">
    Downloads a <code>.tar</code> archive containing a Postgres dump and
    every file under each configured media root. Streaming starts as soon as
    <code>pg_dump</code> begins producing output. Scheduled backups + restore
    are tracked for v0.1.1.
  </p>
  <a class="btn btn-primary" href="/api/admin/backup" download>Download backup</a>
</StatusBlock>

<StatusBlock title="Environment">
  <p class="hint">
    Secrets ending in <code>_KEY</code>, <code>_SECRET</code>,
    <code>_TOKEN</code>, <code>_PASSWORD</code>, <code>_HOOK_SECRET</code> are
    redacted.
  </p>
  <AdminTable columns={["Name", "Value"]}>
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
