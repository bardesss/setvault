<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api/client.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import AdminForm from "#lib/components/AdminForm.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { _, locale } from "svelte-i18n";
  import { fmtLocalDateTime } from "#lib/format.ts";

  interface WatchFolder {
    id: string;
    name: string;
    host_path: string;
    target_media_root_id: string;
    enabled: boolean;
    last_event_at: string | null;
    last_health_check_at: string | null;
    last_health_status: string;
    created_at: string;
  }

  interface MediaRoot {
    id: string;
    name: string;
  }

  let items: WatchFolder[] = [];
  let roots: MediaRoot[] = [];
  let loading = true;
  let error: string | null = null;
  let busy: Record<string, boolean> = {};

  let creating = false;
  let draft = newDraft();

  function newDraft() {
    return {
      name: "",
      host_path: "",
      target_media_root_id: "",
      enabled: true,
    };
  }

  async function load() {
    loading = true;
    try {
      const [list, mrList] = await Promise.all([
        api<{ items: WatchFolder[] }>("/api/admin/watch-folders"),
        api<{ items: MediaRoot[] }>("/api/media-roots"),
      ]);
      items = list.items;
      roots = mrList.items;
      if (!draft.target_media_root_id && roots[0]) {
        draft.target_media_root_id = roots[0].id;
      }
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "load failed";
    } finally {
      loading = false;
    }
  }

  async function save() {
    error = null;
    try {
      await api("/api/admin/watch-folders", {
        method: "POST",
        body: JSON.stringify(draft),
      });
      creating = false;
      draft = newDraft();
      await load();
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "save failed";
    }
  }

  async function toggle(wf: WatchFolder) {
    busy[wf.id] = true;
    busy = busy;
    try {
      await api(`/api/admin/watch-folders/${wf.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !wf.enabled }),
      });
      await load();
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "toggle failed";
    } finally {
      busy[wf.id] = false;
      busy = busy;
    }
  }

  async function healthCheck(wf: WatchFolder) {
    busy[wf.id] = true;
    busy = busy;
    try {
      await api(`/api/admin/watch-folders/${wf.id}/health-check`, {
        method: "POST",
      });
      await load();
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "health-check failed";
    } finally {
      busy[wf.id] = false;
      busy = busy;
    }
  }

  async function remove(wf: WatchFolder) {
    if (!confirm(`Delete watch folder "${wf.name}"?`)) return;
    busy[wf.id] = true;
    busy = busy;
    try {
      await api(`/api/admin/watch-folders/${wf.id}`, { method: "DELETE" });
      items = items.filter((i) => i.id !== wf.id);
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "delete failed";
    } finally {
      busy[wf.id] = false;
      busy = busy;
    }
  }

  function rootName(id: string): string {
    return roots.find((r) => r.id === id)?.name ?? id.slice(0, 8);
  }

  onMount(load);
</script>

<section class="watch-folders">
  <header>
    <h2>Watch folders</h2>
    <p class="muted">
      Filesystem paths the watcher subscribes to. New audio files appearing
      in a watched folder enter the ingest pipeline automatically (filename
      patterns become drafts; ambiguous files land in the Unmatched inbox).
    </p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  <button
    type="button"
    class="btn add"
    on:click={() => { draft = newDraft(); if (roots[0]) draft.target_media_root_id = roots[0].id; creating = true; }}
  >+ New watch folder</button>

  {#if creating}
    <AdminForm on:submit={save}>
      <label class="admin-field">
        <span>Name</span>
        <input type="text" bind:value={draft.name} required />
      </label>
      <label class="admin-field">
        <span>Host path</span>
        <input type="text" bind:value={draft.host_path} required placeholder="/srv/watch/incoming" />
      </label>
      <label class="admin-field">
        <span>Target media root</span>
        <select bind:value={draft.target_media_root_id} required>
          {#each roots as r (r.id)}
            <option value={r.id}>{r.name}</option>
          {/each}
        </select>
      </label>
      <svelte:fragment slot="actions">
        <button type="submit" class="btn btn-primary">Save</button>
        <button type="button" class="btn" on:click={() => { creating = false; }}>Cancel</button>
      </svelte:fragment>
    </AdminForm>
  {/if}

  {#if loading}
    <p class="loading">{$_("common.loading")}</p>
  {:else if items.length === 0}
    <EmptyState message="No watch folders configured yet." />
  {:else}
    <AdminTable
      columns={[
        "Name",
        "Host path",
        "Target root",
        "Enabled",
        "Health",
        "Last event",
        "Actions",
      ]}
    >
      {#each items as wf (wf.id)}
        <tr class:is-disabled={!wf.enabled}>
          <td>{wf.name}</td>
          <td class="mono">{wf.host_path}</td>
          <td>{rootName(wf.target_media_root_id)}</td>
          <td>{wf.enabled ? "✓" : "—"}</td>
          <td class="mono">{wf.last_health_status}</td>
          <td class="mono">{fmtLocalDateTime(wf.last_event_at, $locale) || "—"}</td>
          <td class="cell-actions">
            <button type="button" class="btn btn-sm" disabled={busy[wf.id]} on:click={() => healthCheck(wf)}>Probe</button>
            <button type="button" class="btn btn-sm" disabled={busy[wf.id]} on:click={() => toggle(wf)}>
              {wf.enabled ? "Disable" : "Enable"}
            </button>
            <button type="button" class="btn btn-sm btn-danger" disabled={busy[wf.id]} on:click={() => remove(wf)}>Delete</button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<style>
  .watch-folders { display: grid; gap: var(--sp-3); }
  header { display: grid; gap: var(--sp-1); }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
  .loading { color: var(--text-faint); }
  .add { justify-self: start; }
</style>
