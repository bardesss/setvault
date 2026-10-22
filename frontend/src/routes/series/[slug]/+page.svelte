<!-- frontend/src/routes/series/[slug]/+page.svelte -->
<script lang="ts">
  import { _ } from "svelte-i18n";
  import EntitySetsGrid from "#lib/components/EntitySetsGrid.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { patchSeries } from "#lib/api/catalog.ts";
  import { ApiError } from "#lib/api/client.ts";
  import type { PageData } from "./$types";

  export let data: PageData;
  $: series = data.series;
  let editing = false, busy = false;
  let saveError: string | null = null;
  let form = { name: "", description: "" };
  function startEdit() { form = { name: series.name, description: series.description ?? "" }; editing = true; }
  async function save() {
    saveError = null;
    busy = true;
    try {
      series = await patchSeries(series.slug, { name: form.name, description: form.description || null });
      editing = false;
    } catch (e) {
      saveError = e instanceof ApiError ? e.detail : "Save failed";
    } finally { busy = false; }
  }
</script>

<svelte:head><title>{series.name} — SetVault</title></svelte:head>

<article class="entity-detail">
  <header class="entity-head">
    <h1>{series.name}</h1>
    {#if !editing}<button class="btn btn-ghost" on:click={startEdit}>{$_("catalog.edit")}</button>{/if}
  </header>
  {#if editing}
    <form class="entity-edit" on:submit|preventDefault={save}>
      <label>{$_("catalog.name")}<input bind:value={form.name} required /></label>
      <label>{$_("catalog.description")}<textarea bind:value={form.description}></textarea></label>
      {#if saveError}<p class="error" role="alert">{saveError}</p>{/if}
      <div class="actions">
        <button class="btn btn-primary" type="submit" disabled={busy}>{$_("catalog.save")}</button>
        <button class="btn btn-ghost" type="button" on:click={() => (editing = false)}>{$_("catalog.cancel")}</button>
      </div>
    </form>
  {:else if series.description}<p>{series.description}</p>{/if}
  <h2>{$_("catalog.sets")}</h2>
  {#if data.sets.length}<EntitySetsGrid sets={data.sets} />{:else}<EmptyState message={$_("catalog.no_sets")} />{/if}
</article>

<style>
  .entity-detail { padding: var(--sp-6); display: grid; gap: var(--sp-4); max-width: 900px; }
  .entity-head { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-2); }
  .entity-edit { display: grid; gap: var(--sp-3); max-width: 480px; }
  .entity-edit label { display: grid; gap: var(--sp-1); }
  .actions { display: flex; gap: var(--sp-2); }
  .error { color: var(--accent-error); font-size: var(--ts-sm); }
</style>
