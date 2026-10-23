<!-- frontend/src/routes/venues/[slug]/+page.svelte -->
<script lang="ts">
  import { _ } from "svelte-i18n";
  import EntitySetsGrid from "#lib/components/EntitySetsGrid.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { patchVenue } from "#lib/api/catalog.ts";
  import { ApiError } from "#lib/api/client.ts";
  import MonitorButton from "#lib/components/MonitorButton.svelte";
  import { session } from "#lib/stores/session.ts";
  import type { PageData } from "./$types";

  export let data: PageData;
  $: venue = data.venue;
  let editing = false, busy = false;
  let saveError: string | null = null;
  let form = { name: "", city_or_area: "", country: "", website: "" };
  function startEdit() {
    form = { name: venue.name, city_or_area: venue.city_or_area ?? "", country: venue.country ?? "", website: venue.website ?? "" };
    editing = true;
  }
  async function save() {
    saveError = null;
    busy = true;
    try {
      venue = await patchVenue(venue.slug, {
        name: form.name,
        city_or_area: form.city_or_area || null,
        country: form.country || null,
        website: form.website || null,
      });
      editing = false;
    } catch (e) {
      saveError = e instanceof ApiError ? e.detail : "Save failed";
    } finally { busy = false; }
  }
</script>

<svelte:head><title>{venue.name} — SetVault</title></svelte:head>

<article class="entity-detail">
  <header class="entity-head">
    <h1>{venue.name}</h1>
    {#if !editing}
      {#if $session?.role === "admin"}
        <MonitorButton kind="venue" entityId={venue.id} name={venue.name} monitor={data.venue.monitor ?? null} />
      {/if}
      <button class="btn btn-ghost" on:click={startEdit}>{$_("catalog.edit")}</button>{/if}
  </header>

  {#if editing}
    <form class="entity-edit" on:submit|preventDefault={save}>
      <label>{$_("catalog.name")}<input bind:value={form.name} required /></label>
      <label>{$_("catalog.city")}<input bind:value={form.city_or_area} /></label>
      <label>{$_("catalog.country")}<input bind:value={form.country} maxlength="8" /></label>
      <label>{$_("catalog.website")}<input bind:value={form.website} /></label>
      {#if saveError}<p class="error" role="alert">{saveError}</p>{/if}
      <div class="actions">
        <button class="btn btn-primary" type="submit" disabled={busy}>{$_("catalog.save")}</button>
        <button class="btn btn-ghost" type="button" on:click={() => (editing = false)}>{$_("catalog.cancel")}</button>
      </div>
    </form>
  {:else}
    <p class="muted">{venue.kind}{#if venue.city_or_area} · {venue.city_or_area}{/if}{#if venue.country} · {venue.country}{/if}</p>
    {#if venue.website}<p><a href={venue.website} rel="noreferrer noopener" target="_blank">{venue.website}</a></p>{/if}
  {/if}

  <h2>{$_("catalog.sets")}</h2>
  {#if data.sets.length}<EntitySetsGrid sets={data.sets} />{:else}<EmptyState message={$_("catalog.no_sets")} />{/if}
</article>

<style>
  .entity-detail { padding: var(--sp-6); display: grid; gap: var(--sp-4); max-width: 900px; }
  .entity-head { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-2); }
  .entity-edit { display: grid; gap: var(--sp-3); max-width: 480px; }
  .entity-edit label { display: grid; gap: var(--sp-1); }
  .actions { display: flex; gap: var(--sp-2); }
  .muted { color: var(--text-faint); }
  .error { color: var(--accent-error); font-size: var(--ts-sm); }
</style>
