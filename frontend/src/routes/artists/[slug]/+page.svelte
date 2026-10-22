<script lang="ts">
  import { _ } from "svelte-i18n";
  import EntitySetsGrid from "#lib/components/EntitySetsGrid.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { patchArtist } from "#lib/api/catalog.ts";
  import { enrichArtist } from "#lib/api/catalog_admin.ts";
  import { ApiError } from "#lib/api/client.ts";
  import type { PageData } from "./$types";

  export let data: PageData;
  $: artist = data.artist;

  let editing = false;
  let busy = false;
  let saveError: string | null = null;
  let form = { name: "", country: "", bio: "" };
  function startEdit() {
    form = { name: artist.name, country: artist.country ?? "", bio: artist.bio ?? "" };
    editing = true;
  }
  async function save() {
    saveError = null;
    busy = true;
    try {
      artist = await patchArtist(artist.slug, {
        name: form.name,
        country: form.country || null,
        bio: form.bio || null,
      });
      editing = false;
    } catch (e) {
      saveError = e instanceof ApiError ? e.detail : "Save failed";
    } finally {
      busy = false;
    }
  }

  let enriching = false;
  let enrichError: string | null = null;
  async function enrich() {
    enrichError = null;
    enriching = true;
    try {
      await enrichArtist(artist.slug);
      location.reload();
    } catch (e) {
      enrichError = e instanceof ApiError ? e.detail : "Enrich failed";
    } finally {
      enriching = false;
    }
  }
</script>

<svelte:head><title>{artist.name} — SetVault</title></svelte:head>

<article class="entity-detail">
  <header class="entity-head">
    <h1>{artist.name}</h1>
    {#if !editing}
      <button class="btn btn-ghost" on:click={startEdit}>{$_("catalog.edit")}</button>
      <button class="btn btn-ghost" on:click={enrich} disabled={enriching}>{$_("catalog.enrich")}</button>
    {/if}
  </header>

  {#if enrichError}<p class="error" role="alert">{enrichError}</p>{/if}

  {#if editing}
    <form class="entity-edit" on:submit|preventDefault={save}>
      <label>{$_("catalog.name")}<input bind:value={form.name} required /></label>
      <label>{$_("catalog.country")}<input bind:value={form.country} maxlength="8" /></label>
      <label>{$_("catalog.bio")}<textarea bind:value={form.bio}></textarea></label>
      {#if saveError}<p class="error" role="alert">{saveError}</p>{/if}
      <div class="actions">
        <button class="btn btn-primary" type="submit" disabled={busy}>{$_("catalog.save")}</button>
        <button class="btn btn-ghost" type="button" on:click={() => (editing = false)}>{$_("catalog.cancel")}</button>
      </div>
    </form>
  {:else}
    {#if artist.bio}<p class="bio">{artist.bio}</p>{/if}
    {#if artist.country}<p class="muted">{artist.country}</p>{/if}
  {/if}

  <h2>{$_("catalog.sets")}</h2>
  {#if data.sets.length}
    <EntitySetsGrid sets={data.sets} />
  {:else}
    <EmptyState message={$_("catalog.no_sets")} />
  {/if}
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
