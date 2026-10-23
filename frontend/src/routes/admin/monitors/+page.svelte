<script lang="ts">
  import { _, locale } from "svelte-i18n";
  import { onMount } from "svelte";
  import AdminTable from "#lib/components/AdminTable.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { listSources, type SourceState } from "#lib/api/ingest_sources.ts";
  import {
    createMonitor,
    deleteMonitor,
    updateMonitor,
    type Monitor,
  } from "#lib/api/monitors.ts";
  import { ApiError } from "#lib/api/client.ts";
  import type { PageData } from "./$types";

  export let data: PageData;
  let monitors: Monitor[] = data.monitors;
  let kind: "query" | "entity" = "query";
  let queryText = "";
  let sourceKind = "";
  let externalId = "";
  let sources: SourceState[] = [];
  let errorMsg: string | null = null;
  let busy = false;

  onMount(async () => {
    try {
      sources = (await listSources()).filter((s) => s.enabled);
    } catch {
      errorMsg = $_("monitors.load_sources_error");
    }
  });

  function msg(e: unknown): string {
    return e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "failed";
  }

  $: helpKey = ["youtube", "soundcloud"].includes(sourceKind)
    ? `monitors.help_${sourceKind}`
    : "monitors.help_generic";
  $: canAdd =
    kind === "query"
      ? queryText.trim() !== ""
      : sourceKind !== "" && externalId.trim() !== "";

  async function add() {
    if (!canAdd) return;
    busy = true;
    errorMsg = null;
    try {
      const m = await createMonitor(
        kind === "query"
          ? {
              kind,
              query_text: queryText.trim(),
              source_kind: sourceKind || null,
            }
          : {
              kind,
              source_kind: sourceKind,
              external_id: externalId.trim(),
            },
      );
      monitors = [m, ...monitors.filter((x) => x.id !== m.id)];
      queryText = "";
      sourceKind = "";
      externalId = "";
    } catch (e) {
      errorMsg = msg(e);
    } finally {
      busy = false;
    }
  }

  function replace(updated: Monitor) {
    monitors = monitors.map((x) => (x.id === updated.id ? updated : x));
  }

  async function toggle(m: Monitor) {
    errorMsg = null;
    try {
      replace(await updateMonitor(m.id, { enabled: !m.enabled }));
    } catch (e) {
      errorMsg = msg(e);
    }
  }

  async function setCap(m: Monitor, ev: Event) {
    const input = ev.currentTarget as HTMLInputElement;
    const cap = Number(input.value);
    if (!Number.isInteger(cap) || cap < 1 || cap > 50) {
      input.value = String(m.per_poll_cap);
      errorMsg = $_("monitors.cap_label");
      return;
    }
    if (cap === m.per_poll_cap) return;
    errorMsg = null;
    try {
      replace(await updateMonitor(m.id, { per_poll_cap: cap }));
    } catch (e) {
      input.value = String(m.per_poll_cap);
      errorMsg = msg(e);
    }
  }

  async function remove(m: Monitor) {
    errorMsg = null;
    try {
      await deleteMonitor(m.id);
      monitors = monitors.filter((x) => x.id !== m.id);
    } catch (e) {
      errorMsg = msg(e);
    }
  }

  const UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  function ago(iso: string | null, loc: string | null | undefined): string {
    if (!iso) return $_("monitors.never");
    const secs = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
    const rtf = new Intl.RelativeTimeFormat(loc || "en", { numeric: "auto" });
    for (const [unit, size] of UNITS) {
      if (Math.abs(secs) >= size) return rtf.format(Math.round(secs / size), unit);
    }
    return rtf.format(0, "second");
  }

  const ENTITY_PATH = { artist: "artists", party: "parties", venue: "venues" };
</script>

<svelte:head><title>{$_("monitors.admin_title")} - SetVault</title></svelte:head>

<section>
  <h1>{$_("monitors.admin_title")}</h1>

  {#if errorMsg}
    <p class="admin-msg is-error" role="alert">{errorMsg}</p>
  {/if}

  <form class="add" on:submit|preventDefault={add}>
    <label class="field">
      <span>{$_("monitors.kind_label")}</span>
      <select bind:value={kind} aria-label={$_("monitors.kind_label")}>
        <option value="query">{$_("monitors.kind_query")}</option>
        <option value="entity">{$_("monitors.kind_entity")}</option>
      </select>
    </label>
    {#if kind === "query"}
      <input
        type="text"
        bind:value={queryText}
        placeholder={$_("monitors.query_placeholder")}
        aria-label={$_("monitors.query_placeholder")}
      />
    {/if}
    <label class="field">
      <span>{$_("monitors.source_label")}</span>
      <select bind:value={sourceKind} aria-label={$_("monitors.source_label")}>
        {#if kind === "query"}
          <option value="">{$_("monitors.source_all")}</option>
        {:else}
          <option value="" disabled>{$_("monitors.source_pick")}</option>
        {/if}
        {#each sources as s (s.kind)}
          <option value={s.kind}>{s.name}</option>
        {/each}
      </select>
    </label>
    {#if kind === "entity"}
      <label class="field grow">
        <span>{$_("monitors.external_id")}</span>
        <input
          type="text"
          bind:value={externalId}
          aria-label={$_("monitors.external_id")}
        />
        <small class="help">{$_(helpKey)}</small>
      </label>
    {/if}
    <button class="btn" type="submit" disabled={busy || !canAdd}>{$_("monitors.add")}</button>
  </form>

  {#if monitors.length === 0}
    <EmptyState message={$_("monitors.empty")} />
  {:else}
    <AdminTable
      columns={[
        $_("monitors.col_query"),
        $_("monitors.col_source"),
        $_("monitors.col_cap"),
        $_("monitors.col_last_checked"),
        $_("monitors.col_enabled"),
        "",
      ]}
    >
      {#each monitors as m (m.id)}
        <tr class:is-disabled={!m.enabled}>
          <td>
            {m.query_text ?? m.external_id}
            {#if m.catalog_kind && m.catalog_slug}
              <a class="linked" href={`/${ENTITY_PATH[m.catalog_kind]}/${m.catalog_slug}`}>
                {$_("monitors.linked_to")} {m.catalog_name}
              </a>
            {/if}
          </td>
          <td class="mono">{m.source_kind ?? $_("monitors.all_sources")}</td>
          <td>
            <input
              class="cap"
              type="number"
              min="1"
              max="50"
              value={m.per_poll_cap}
              aria-label={$_("monitors.cap_label")}
              on:change={(ev) => setCap(m, ev)}
            />
          </td>
          <td class="mono" title={m.last_checked_at ?? ""}>{ago(m.last_checked_at, $locale)}</td>
          <td>{m.enabled ? "✓" : "—"}</td>
          <td class="cell-actions">
            <button type="button" class="btn btn-sm" on:click={() => toggle(m)}>
              {m.enabled ? $_("monitors.disable") : $_("monitors.enable")}
            </button>
            <button type="button" class="btn btn-sm" on:click={() => remove(m)}>
              {$_("monitors.delete")}
            </button>
          </td>
        </tr>
      {/each}
    </AdminTable>
  {/if}
</section>

<style>
  section { display: grid; gap: var(--sp-4); }
  .add { display: flex; gap: var(--sp-2); flex-wrap: wrap; align-items: flex-end; }
  .add > input { flex: 1 1 200px; }
  .field { display: grid; gap: var(--sp-1); font-size: var(--ts-sm); }
  .field.grow { flex: 1 1 200px; }
  .help { color: var(--text-muted); }
  .linked { display: block; font-size: var(--ts-sm); color: var(--text-muted); }
  .cap { width: 4.5em; }
</style>
