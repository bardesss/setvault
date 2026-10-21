<script lang="ts">
  import { _ } from "svelte-i18n";
  import {
    testProvider,
    upsertProvider,
    type ProviderConfig,
    type ProviderKind,
  } from "#lib/api/providers.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import AdminForm from "#lib/components/AdminForm.svelte";
  import type { PageData } from "./$types";

  export let data: PageData;
  let providers: ProviderConfig[] = data.providers;
  let kind: ProviderKind = "musicbrainz";
  let configFields: Record<string, string> = {};
  let saving = false;
  let testResult: string | null = null;

  const SCHEMAS: Record<ProviderKind, { key: string; label: string }[]> = {
    musicbrainz: [{ key: "user_agent", label: "User-Agent (per MB ToS)" }],
    discogs: [{ key: "token", label: "Personal access token" }],
    acoustid: [{ key: "api_key", label: "Application API key" }],
  };
  $: configSchema = SCHEMAS[kind];

  async function save() {
    saving = true;
    try {
      const out = await upsertProvider(kind, { config: configFields, enabled: true });
      providers = [...providers.filter((p) => p.provider_kind !== kind), out];
    } finally {
      saving = false;
    }
  }

  async function runTest(k: ProviderKind) {
    const r = await testProvider(k);
    testResult = r.ok ? "ok" : (r.error ?? "failed");
  }
</script>

<svelte:head><title>{$_("admin.providers.title")} - SetVault</title></svelte:head>

<section>
  <h1>{$_("admin.providers.title")}</h1>

  <AdminTable
    columns={[
      $_("admin.providers.kind"),
      $_("admin.providers.enabled"),
      $_("admin.providers.priority"),
      $_("admin.providers.actions"),
    ]}
  >
    {#each providers as p (p.id)}
      <tr>
        <td>{p.provider_kind}</td>
        <td>{p.enabled ? "OK" : "off"}</td>
        <td>{p.priority}</td>
        <td class="cell-actions">
          <button class="btn btn-sm" on:click={() => runTest(p.provider_kind)}>
            {$_("admin.providers.test")}
          </button>
        </td>
      </tr>
    {/each}
  </AdminTable>

  <AdminForm title={$_("admin.providers.add_or_update")} on:submit={save}>
    <label class="admin-field">
      <span>{$_("admin.providers.kind")}</span>
      <select bind:value={kind}>
        <option value="musicbrainz">MusicBrainz</option>
        <option value="discogs">Discogs</option>
        <option value="acoustid">AcoustID</option>
      </select>
    </label>
    {#each configSchema as f (f.key)}
      <label class="admin-field">
        <span>{f.label}</span>
        <input type="text" bind:value={configFields[f.key]} />
      </label>
    {/each}
    <svelte:fragment slot="actions">
      <button type="submit" class="btn btn-primary" disabled={saving}>
        {$_("admin.providers.save")}
      </button>
    </svelte:fragment>
  </AdminForm>
  {#if testResult}<p class="admin-msg">Test: {testResult}</p>{/if}
</section>

<style>
  section { display: grid; gap: var(--sp-4); }
</style>
