<script lang="ts">
  import { onMount } from "svelte";
  import { ApiError } from "#lib/api/client.ts";
  import {
    createWebhook,
    deleteWebhook,
    listDeliveries,
    listWebhooks,
    patchWebhook,
    rotateWebhookSecret,
    testWebhook,
    type Webhook,
    type WebhookCreate,
    type WebhookDelivery,
  } from "#lib/api/webhooks.ts";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import AdminForm from "#lib/components/AdminForm.svelte";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import Modal from "#lib/components/Modal.svelte";
  import { _, locale } from "svelte-i18n";
  import { fmtLocalDateTime } from "#lib/format.ts";
  import { toast } from "#lib/stores/toast.ts";

  // webhook.test is internal: it can be sent but not subscribed to.
  const KNOWN_EVENTS = [
    "set.published",
    "set.updated",
    "set.deleted",
    "set.restored",
    "set.purged",
  ];

  const REFRESH_EVENTS = ["set.published", "set.deleted", "set.restored", "set.purged"];

  interface Recipe {
    label: string;
    name: string;
    preset: Partial<WebhookCreate>;
  }

  const RECIPES: Recipe[] = [
    {
      label: "admin.webhooks.recipe_plex",
      name: "admin.webhooks.recipe_plex_name",
      preset: {
        target_url: "http://plex.local:32400/library/sections/1/refresh",
        events: REFRESH_EVENTS,
        headers: { "X-Plex-Token": "YOUR_TOKEN" },
      },
    },
    {
      label: "admin.webhooks.recipe_jellyfin",
      name: "admin.webhooks.recipe_jellyfin_name",
      preset: {
        target_url: "http://jellyfin.local:8096/Library/Refresh",
        events: REFRESH_EVENTS,
      },
    },
    {
      label: "admin.webhooks.recipe_generic",
      name: "admin.webhooks.recipe_generic_name",
      preset: {
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

  interface HeaderRow {
    name: string;
    value: string;
    existing: boolean; // stored on the server; its value is never shown
    removed: boolean;
  }

  let items: Webhook[] = [];
  let loading = true;
  let error: string | null = null;
  let busy: Record<string, boolean> = {};

  let creating = false;
  let draft = newDraft();
  let draftHeaders: HeaderRow[] = [];

  let editingId: string | null = null;
  let editRows: HeaderRow[] = [];

  let openDeliveries: Record<string, boolean> = {};
  let deliveries: Record<string, WebhookDelivery[]> = {};
  let deliveriesError: Record<string, boolean> = {};

  let secretShown: string | null = null;
  let deleteTarget: Webhook | null = null;
  let rotateTarget: Webhook | null = null;

  function newDraft(): WebhookCreate {
    return {
      name: "",
      target_url: "",
      events: [],
      body_template: null,
      headers: {},
      enabled: true,
    };
  }

  function errMsg(e: unknown, fallback: string): string {
    return e instanceof ApiError ? e.detail : fallback;
  }

  async function load() {
    loading = true;
    try {
      items = await listWebhooks();
    } catch (e) {
      error = errMsg(e, $_("admin.webhooks.load_failed"));
    } finally {
      loading = false;
    }
  }

  async function save() {
    error = null;
    const headers: Record<string, string> = {};
    for (const r of draftHeaders) {
      if (r.name.trim() && r.value) headers[r.name.trim()] = r.value;
    }
    try {
      const created = await createWebhook({ ...draft, headers });
      creating = false;
      draft = newDraft();
      draftHeaders = [];
      secretShown = created.secret;
      await load();
    } catch (e) {
      error = errMsg(e, $_("admin.webhooks.save_failed"));
    }
  }

  async function run(wh: Webhook, fn: () => Promise<void>) {
    busy[wh.id] = true;
    busy = busy;
    error = null;
    try {
      await fn();
    } catch (e) {
      error = errMsg(e, $_("admin.webhooks.action_failed"));
    } finally {
      busy[wh.id] = false;
      busy = busy;
    }
  }

  async function toggleEnabled(wh: Webhook) {
    await run(wh, async () => {
      await patchWebhook(wh.id, { enabled: !wh.enabled });
      await load();
    });
  }

  async function confirmDelete() {
    const wh = deleteTarget;
    deleteTarget = null;
    if (!wh) return;
    await run(wh, async () => {
      await deleteWebhook(wh.id);
      items = items.filter((i) => i.id !== wh.id);
    });
  }

  async function confirmRotate() {
    const wh = rotateTarget;
    rotateTarget = null;
    if (!wh) return;
    await run(wh, async () => {
      secretShown = (await rotateWebhookSecret(wh.id)).secret;
    });
  }

  async function test(wh: Webhook) {
    await run(wh, async () => {
      await testWebhook(wh.id);
      toast.success($_("admin.webhooks.test_queued"));
      if (openDeliveries[wh.id]) await loadDeliveries(wh.id);
    });
  }

  function startEdit(wh: Webhook) {
    editingId = wh.id;
    editRows = wh.header_names.map((name) => ({
      name,
      value: "",
      existing: true,
      removed: false,
    }));
  }

  async function saveHeaders(wh: Webhook) {
    // Only changed keys go out; an untouched stored value is never sent.
    const headers: Record<string, string> = {};
    for (const r of editRows) {
      const name = r.name.trim();
      if (!name) continue;
      if (r.removed) headers[name] = "";
      else if (r.value) headers[name] = r.value;
    }
    if (Object.keys(headers).length === 0) {
      editingId = null;
      return;
    }
    await run(wh, async () => {
      await patchWebhook(wh.id, { headers });
      editingId = null;
      toast.success($_("admin.webhooks.headers_saved"));
      await load();
    });
  }

  function addRow(rows: HeaderRow[]): HeaderRow[] {
    return [...rows, { name: "", value: "", existing: false, removed: false }];
  }

  function removeRow(rows: HeaderRow[], idx: number): HeaderRow[] {
    if (rows[idx].existing) {
      return rows.map((x, i) => (i === idx ? { ...x, removed: !x.removed } : x));
    }
    return rows.filter((_x, i) => i !== idx);
  }

  async function loadDeliveries(id: string) {
    deliveriesError[id] = false;
    try {
      deliveries[id] = await listDeliveries(id);
    } catch {
      deliveriesError[id] = true;
    }
    deliveries = deliveries;
    deliveriesError = deliveriesError;
  }

  async function toggleDeliveries(wh: Webhook) {
    openDeliveries[wh.id] = !openDeliveries[wh.id];
    openDeliveries = openDeliveries;
    if (openDeliveries[wh.id]) await loadDeliveries(wh.id);
  }

  async function copySecret() {
    if (!secretShown) return;
    try {
      await navigator.clipboard.writeText(secretShown);
      toast.success($_("admin.webhooks.copied"));
    } catch {
      // clipboard blocked: the field is selectable
    }
  }

  function applyRecipe(r: Recipe) {
    const { headers, ...rest } = r.preset;
    draft = { ...newDraft(), ...rest, name: $_(r.name) };
    draftHeaders = Object.entries(headers ?? {}).map(([name, value]) => ({
      name,
      value,
      existing: false,
      removed: false,
    }));
    creating = true;
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

  function result(d: WebhookDelivery): string {
    if (d.error) return d.error;
    return d.status_code === null ? "—" : String(d.status_code);
  }

  onMount(load);
</script>

<section class="webhooks">
  <header>
    <h2>{$_("admin.webhooks.title")}</h2>
    <p class="muted">{$_("admin.webhooks.intro")}</p>
  </header>

  {#if error}<p class="admin-msg is-error" role="alert">{error}</p>{/if}

  <div class="recipes">
    {#each RECIPES as recipe (recipe.label)}
      <button type="button" class="btn btn-sm" on:click={() => applyRecipe(recipe)}>
        + {$_(recipe.label)}
      </button>
    {/each}
    <button
      type="button"
      class="btn btn-sm"
      on:click={() => { draft = newDraft(); draftHeaders = []; creating = true; }}
    >
      + {$_("admin.webhooks.recipe_empty")}
    </button>
  </div>

  {#if creating}
    <AdminForm on:submit={save}>
      <label class="admin-field">
        <span>{$_("admin.webhooks.name")}</span>
        <input type="text" bind:value={draft.name} required />
      </label>
      <label class="admin-field">
        <span>{$_("admin.webhooks.target_url")}</span>
        <input type="url" bind:value={draft.target_url} required />
      </label>
      <fieldset>
        <legend>{$_("admin.webhooks.events")}</legend>
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
      <fieldset>
        <legend>{$_("admin.webhooks.headers")}</legend>
        {#each draftHeaders as row, i (i)}
          <div class="header-row">
            <input
              type="text"
              data-testid="header-name"
              aria-label={$_("admin.webhooks.header_name")}
              placeholder={$_("admin.webhooks.header_name")}
              bind:value={row.name}
            />
            <input
              type="text"
              data-testid="header-value"
              aria-label={$_("admin.webhooks.header_value")}
              placeholder={$_("admin.webhooks.header_value")}
              autocomplete="off"
              bind:value={row.value}
            />
            <button
              type="button"
              class="btn btn-sm"
              on:click={() => (draftHeaders = removeRow(draftHeaders, i))}
            >{$_("admin.webhooks.remove_header")}</button>
          </div>
        {/each}
        <button type="button" class="btn btn-sm" on:click={() => (draftHeaders = addRow(draftHeaders))}>
          {$_("admin.webhooks.add_header")}
        </button>
      </fieldset>
      <details>
        <summary>{$_("admin.webhooks.body_template")}</summary>
        <textarea
          rows="6"
          placeholder={BODY_PLACEHOLDER}
          on:input={onBodyTemplateInput}
        >{draft.body_template ? JSON.stringify(draft.body_template, null, 2) : ""}</textarea>
      </details>
      <svelte:fragment slot="actions">
        <button type="submit" class="btn btn-primary">{$_("admin.webhooks.save")}</button>
        <button type="button" class="btn" on:click={() => { creating = false; }}>{$_("admin.webhooks.cancel")}</button>
      </svelte:fragment>
    </AdminForm>
  {/if}

  {#if loading}
    <p class="loading">{$_("common.loading")}</p>
  {:else if items.length === 0}
    <EmptyState message={$_("admin.webhooks.empty")} />
  {:else}
    <AdminTable
      columns={[
        $_("admin.webhooks.col_name"),
        $_("admin.webhooks.col_url"),
        $_("admin.webhooks.col_events"),
        $_("admin.webhooks.col_enabled"),
        $_("admin.webhooks.col_last_call"),
        $_("admin.webhooks.col_status"),
        $_("admin.webhooks.col_signing"),
        $_("admin.webhooks.col_actions"),
      ]}
    >
      {#each items as wh (wh.id)}
        <tr class:is-disabled={!wh.enabled}>
          <td>{wh.name}</td>
          <td class="mono ellipsis" title={wh.target_url}>{wh.target_url}</td>
          <td class="mono">{wh.events.join(", ")}</td>
          <td>{wh.enabled ? "✓" : "—"}</td>
          <td class="mono">{fmtLocalDateTime(wh.last_call_at, $locale) || "—"}</td>
          <td class="mono">
            {wh.last_status_code ?? "—"}
            {#if wh.last_error}<span class="err" title={wh.last_error}>!</span>{/if}
          </td>
          <td>{wh.secret_set ? $_("admin.webhooks.signed") : $_("admin.webhooks.not_signed")}</td>
          <td class="cell-actions">
            <button type="button" class="btn btn-sm" disabled={busy[wh.id]} on:click={() => test(wh)}>{$_("admin.webhooks.test")}</button>
            <button type="button" class="btn btn-sm" disabled={busy[wh.id]} on:click={() => toggleEnabled(wh)}>
              {wh.enabled ? $_("admin.webhooks.disable") : $_("admin.webhooks.enable")}
            </button>
            <button type="button" class="btn btn-sm" disabled={busy[wh.id]} on:click={() => startEdit(wh)}>{$_("admin.webhooks.edit_headers")}</button>
            <button type="button" class="btn btn-sm" disabled={busy[wh.id]} on:click={() => (rotateTarget = wh)}>{$_("admin.webhooks.rotate")}</button>
            <button
              type="button"
              class="btn btn-sm"
              aria-expanded={!!openDeliveries[wh.id]}
              on:click={() => toggleDeliveries(wh)}
            >{$_("admin.webhooks.deliveries")}</button>
            <button type="button" class="btn btn-sm btn-danger" disabled={busy[wh.id]} on:click={() => (deleteTarget = wh)}>{$_("admin.webhooks.delete")}</button>
          </td>
        </tr>
        {#if editingId === wh.id}
          <tr>
            <td colspan="8">
              <div class="panel">
                <p class="muted">{$_("admin.webhooks.headers_hint")}</p>
                {#each editRows as row, i (i)}
                  <div class="header-row" class:is-removed={row.removed}>
                    <input
                      type="text"
                      data-testid="header-name"
                      aria-label={$_("admin.webhooks.header_name")}
                      placeholder={$_("admin.webhooks.header_name")}
                      readonly={row.existing}
                      bind:value={row.name}
                    />
                    <input
                      type="text"
                      data-testid="header-value"
                      aria-label={$_("admin.webhooks.header_value")}
                      placeholder={row.existing ? $_("admin.webhooks.header_unchanged") : $_("admin.webhooks.header_value")}
                      autocomplete="off"
                      disabled={row.removed}
                      bind:value={row.value}
                    />
                    <button type="button" class="btn btn-sm" on:click={() => (editRows = removeRow(editRows, i))}>
                      {$_("admin.webhooks.remove_header")}
                    </button>
                  </div>
                {/each}
                <div class="cell-actions">
                  <button type="button" class="btn btn-sm" on:click={() => (editRows = addRow(editRows))}>{$_("admin.webhooks.add_header")}</button>
                  <button type="button" class="btn btn-sm btn-primary" disabled={busy[wh.id]} on:click={() => saveHeaders(wh)}>{$_("admin.webhooks.save_headers")}</button>
                  <button type="button" class="btn btn-sm" on:click={() => (editingId = null)}>{$_("admin.webhooks.cancel")}</button>
                </div>
              </div>
            </td>
          </tr>
        {/if}
        {#if openDeliveries[wh.id]}
          <tr>
            <td colspan="8">
              <div class="panel" data-testid="deliveries-panel">
                {#if deliveriesError[wh.id]}
                  <p class="admin-msg is-error">{$_("admin.webhooks.deliveries_failed")}</p>
                {:else if deliveries[wh.id] === undefined}
                  <p class="loading">{$_("common.loading")}</p>
                {:else if deliveries[wh.id].length === 0}
                  <p class="muted">{$_("admin.webhooks.deliveries_empty")}</p>
                {:else}
                  <table class="deliveries">
                    <thead>
                      <tr>
                        <th>{$_("admin.webhooks.col_time")}</th>
                        <th>{$_("admin.webhooks.col_event")}</th>
                        <th>{$_("admin.webhooks.col_attempt")}</th>
                        <th>{$_("admin.webhooks.col_result")}</th>
                        <th>{$_("admin.webhooks.col_duration")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each deliveries[wh.id] as d (d.delivery_id + ":" + d.attempt)}
                        <tr>
                          <td class="mono">{fmtLocalDateTime(d.created_at, $locale)}</td>
                          <td class="mono">{d.event}</td>
                          <td>{d.attempt}</td>
                          <td class="mono">{result(d)}</td>
                          <td class="mono">{d.duration_ms === null ? "—" : `${d.duration_ms} ms`}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                {/if}
              </div>
            </td>
          </tr>
        {/if}
      {/each}
    </AdminTable>
  {/if}
</section>

<Modal
  open={secretShown !== null}
  title={$_("admin.webhooks.secret_title")}
  on:close={() => (secretShown = null)}
>
  <p>{$_("admin.webhooks.secret_warning")}</p>
  <div class="secret-row">
    <input
      class="secret-field"
      type="text"
      readonly
      data-testid="webhook-secret"
      aria-label={$_("admin.webhooks.secret_label")}
      value={secretShown ?? ""}
      on:focus={(e) => e.currentTarget.select()}
    />
    <button type="button" class="btn" on:click={copySecret}>{$_("admin.webhooks.copy")}</button>
  </div>
  <svelte:fragment slot="actions">
    <button type="button" class="btn btn-primary" on:click={() => (secretShown = null)}>
      {$_("admin.webhooks.close")}
    </button>
  </svelte:fragment>
</Modal>

<ConfirmDialog
  open={deleteTarget !== null}
  title={$_("admin.webhooks.delete_title")}
  message={$_("admin.webhooks.delete_message", { values: { name: deleteTarget?.name ?? "" } })}
  confirmLabel={$_("admin.webhooks.delete")}
  danger
  on:confirm={confirmDelete}
  on:cancel={() => (deleteTarget = null)}
/>

<ConfirmDialog
  open={rotateTarget !== null}
  title={$_("admin.webhooks.rotate_title")}
  message={$_("admin.webhooks.rotate_message", { values: { name: rotateTarget?.name ?? "" } })}
  confirmLabel={$_("admin.webhooks.rotate")}
  on:confirm={confirmRotate}
  on:cancel={() => (rotateTarget = null)}
/>

<style>
  .webhooks { display: grid; gap: var(--sp-3); }
  header { display: grid; gap: var(--sp-1); }
  .muted { color: var(--text-faint); font-size: var(--ts-sm); margin: 0; }
  .loading { color: var(--text-faint); }
  .recipes { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
  .ellipsis { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .err { color: var(--accent-error); font-weight: 700; margin-left: var(--sp-1); }
  .secret-row { display: flex; gap: var(--sp-2); }
  .secret-field { flex: 1; font-family: var(--font-mono, monospace); }
  .header-row { display: flex; gap: var(--sp-2); align-items: center; margin-bottom: var(--sp-1); }
  .header-row.is-removed input { text-decoration: line-through; opacity: 0.5; }
  .panel { display: grid; gap: var(--sp-2); padding: var(--sp-2); }
</style>
