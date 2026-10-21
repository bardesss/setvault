<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError } from "#lib/api/client.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import AdminForm from "#lib/components/AdminForm.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";

  interface Webhook {
    id: string;
    name: string;
    target_url: string;
    events: string[];
    body_template: Record<string, unknown> | null;
    headers: Record<string, string>;
    enabled: boolean;
    last_call_at: string | null;
    last_status_code: number | null;
    last_error: string | null;
  }

  const KNOWN_EVENTS = ["set.published", "set.updated", "set.deleted", "set.purged"];

  const RECIPES: { label: string; preset: Partial<Webhook> }[] = [
    {
      label: "Plex library refresh",
      preset: {
        name: "Plex refresh",
        target_url: "http://plex.local:32400/library/sections/1/refresh?X-Plex-Token=YOUR_TOKEN",
        events: ["set.published", "set.purged"],
        body_template: null,
      },
    },
    {
      label: "Jellyfin library refresh",
      preset: {
        name: "Jellyfin refresh",
        target_url: "http://jellyfin.local:8096/Library/Refresh",
        events: ["set.published", "set.purged"],
        body_template: null,
      },
    },
    {
      label: "Generic JSON POST",
      preset: {
        name: "Generic",
        target_url: "https://example.com/setvault-hook",
        events: ["set.published"],
        body_template: {
          event: "{{event}}",
          slug: "{{slug}}",
          title: "{{title}}",
        },
      },
    },
  ];

  // Placeholder string kept in JS to avoid Svelte parsing `{{event}}` as a
  // template expression.
  const BODY_PLACEHOLDER =
    "{\n  \"event\": \"{{event}}\",\n  \"slug\": \"{{slug}}\",\n  \"title\": \"{{title}}\"\n}";

  let items: Webhook[] = [];
  let loading = true;
  let error: string | null = null;
  let busy: Record<string, boolean> = {};

  let creating = false;
  let draft = newDraft();

  function newDraft(): Partial<Webhook> {
    return {
      name: "",
      target_url: "",
      events: [],
      body_template: null,
      headers: {},
      enabled: true,
    };
  }

  async function load() {
    loading = true;
    try {
      const r = await api<{ items: Webhook[] }>("/api/admin/webhooks");
      items = r.items;
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "load failed";
    } finally {
      loading = false;
    }
  }

  async function save() {
    error = null;
    try {
      await api("/api/admin/webhooks", {
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

  async function toggleEnabled(wh: Webhook) {
    busy[wh.id] = true;
    busy = busy;
    try {
      await api(`/api/admin/webhooks/${wh.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !wh.enabled }),
      });
      await load();
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "toggle failed";
    } finally {
      busy[wh.id] = false;
      busy = busy;
    }
  }

  async function remove(wh: Webhook) {
    if (!confirm(`Delete webhook "${wh.name}"?`)) return;
    busy[wh.id] = true;
    busy = busy;
    try {
      await api(`/api/admin/webhooks/${wh.id}`, { method: "DELETE" });
      items = items.filter((i) => i.id !== wh.id);
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "delete failed";
    } finally {
      busy[wh.id] = false;
      busy = busy;
    }
  }

  async function test(wh: Webhook) {
    busy[wh.id] = true;
    busy = busy;
    try {
      await api(`/api/admin/webhooks/${wh.id}/test`, { method: "POST" });
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "test failed";
    } finally {
      busy[wh.id] = false;
      busy = busy;
    }
  }

  function applyRecipe(preset: Partial<Webhook>) {
    draft = { ...newDraft(), ...preset };
    creating = true;
  }

  function fmtDate(iso: string | null): string {
    if (!iso) return "—";
    return iso.slice(0, 16).replace("T", " ");
  }

  function toggleEvent(ev: string) {
    const events = draft.events ?? [];
    draft = {
      ...draft,
      events: events.includes(ev) ? events.filter((e) => e !== ev) : [...events, ev],
    };
  }

  function onBodyTemplateInput(ev: Event) {
    const raw = (ev.target as HTMLTextAreaElement).value;
    try {
      draft = { ...draft, body_template: raw ? JSON.parse(raw) : null };
    } catch {
      // keep typing; validated on save
    }
  }

  onMount(load);
</script>

<section class="webhooks">
  <header>
    <h2>Library refresh webhooks</h2>
    <p class="muted">
      Fires an HTTP POST to a configured URL whenever a matching audit event
      occurs (set publish / purge etc.). Plex / Jellyfin / Emby use this to
      refresh their library after SetVault publishes new content.
    </p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  <div class="recipes">
    {#each RECIPES as recipe (recipe.label)}
      <button type="button" class="btn btn-sm" on:click={() => applyRecipe(recipe.preset)}>
        + {recipe.label}
      </button>
    {/each}
    <button type="button" class="btn btn-sm" on:click={() => { draft = newDraft(); creating = true; }}>
      + Empty
    </button>
  </div>

  {#if creating}
    <AdminForm on:submit={save}>
      <label class="admin-field">
        <span>Name</span>
        <input type="text" bind:value={draft.name} required />
      </label>
      <label class="admin-field">
        <span>Target URL</span>
        <input type="url" bind:value={draft.target_url} required />
      </label>
      <fieldset>
        <legend>Events</legend>
        {#each KNOWN_EVENTS as ev (ev)}
          <label class="admin-field inline">
            <input
              type="checkbox"
              checked={draft.events?.includes(ev)}
              on:change={() => toggleEvent(ev)}
            />
            <code>{ev}</code>
          </label>
        {/each}
      </fieldset>
      <details>
        <summary>Advanced: body template (JSON)</summary>
        <textarea
          rows="6"
          placeholder={BODY_PLACEHOLDER}
          on:input={onBodyTemplateInput}
        >{draft.body_template ? JSON.stringify(draft.body_template, null, 2) : ""}</textarea>
      </details>
      <svelte:fragment slot="actions">
        <button type="submit" class="btn btn-primary">Save</button>
        <button type="button" class="btn" on:click={() => { creating = false; }}>Cancel</button>
      </svelte:fragment>
    </AdminForm>
  {/if}

  {#if loading}
    <p class="loading">Loading…</p>
  {:else if items.length === 0}
    <EmptyState message="No webhooks configured yet." />
  {:else}
    <AdminTable
      columns={[
        "Name",
        "URL",
        "Events",
        "Enabled",
        "Last call",
        "Status",
        "Actions",
      ]}
    >
      {#each items as wh (wh.id)}
        <tr class:is-disabled={!wh.enabled}>
          <td>{wh.name}</td>
          <td class="mono ellipsis" title={wh.target_url}>{wh.target_url}</td>
          <td class="mono">{wh.events.join(", ")}</td>
          <td>{wh.enabled ? "✓" : "—"}</td>
          <td class="mono">{fmtDate(wh.last_call_at)}</td>
          <td class="mono">
            {wh.last_status_code ?? "—"}
            {#if wh.last_error}<span class="err" title={wh.last_error}>!</span>{/if}
          </td>
          <td class="cell-actions">
            <button type="button" class="btn btn-sm" disabled={busy[wh.id]} on:click={() => test(wh)}>Test</button>
            <button type="button" class="btn btn-sm" disabled={busy[wh.id]} on:click={() => toggleEnabled(wh)}>
              {wh.enabled ? "Disable" : "Enable"}
            </button>
            <button type="button" class="btn btn-sm btn-danger" disabled={busy[wh.id]} on:click={() => remove(wh)}>Delete</button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<style>
  .webhooks { display: grid; gap: var(--sp-3); }
  header { display: grid; gap: var(--sp-1); }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
  .loading { color: var(--text-faint); }
  .recipes { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
  .ellipsis { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .err { color: var(--accent-error); font-weight: 700; margin-left: var(--sp-1); }
</style>
