<!-- frontend/src/routes/parties/[slug]/+page.svelte -->
<script lang="ts">
  import { _ } from "svelte-i18n";
  import EntitySetsGrid from "#lib/components/EntitySetsGrid.svelte";
  import EmptyState from "#lib/components/EmptyState.svelte";
  import { createSeries, createVenue, patchParty } from "#lib/api/catalog.ts";
  import { ApiError } from "#lib/api/client.ts";
  import { formatDetail } from "#lib/api/errors.ts";
  import type { LookupRow } from "#lib/api/lookup.ts";
  import EntityPicker from "#lib/components/EntityPicker.svelte";
  import MonitorButton from "#lib/components/MonitorButton.svelte";
  import { session } from "#lib/stores/session.ts";
  import { toast } from "#lib/stores/toast.ts";
  import type { PageData } from "./$types";

  export let data: PageData;
  $: party = data.party;
  let editing = false, busy = false;
  let saveError: string | null = null;
  let form = { name: "", date: "", description: "" };
  let venue: LookupRow[] = [];
  let series: LookupRow[] = [];
  const asRow = (e: { id: string; name: string; slug: string }): LookupRow => ({ ...e, hint: null });
  function startEdit() {
    form = { name: party.name, date: party.date ?? "", description: party.description ?? "" };
    venue = party.venue ? [asRow(party.venue)] : [];
    series = party.series ? [asRow(party.series)] : [];
    editing = true;
  }
  async function onCreate(ev: CustomEvent<{ name: string }>, kind: "venue" | "series") {
    const { name } = ev.detail;
    try {
      if (kind === "venue") venue = [asRow(await createVenue(name))];
      else series = [asRow(await createSeries(name))];
    } catch (e) {
      const error = e instanceof ApiError ? formatDetail(e.detail) : String(e);
      toast.error($_("catalog.create_failed", { values: { name, error } }));
    }
  }
  async function save() {
    saveError = null;
    busy = true;
    try {
      party = await patchParty(party.slug, {
        name: form.name, date: form.date || null, description: form.description || null,
        venue_id: venue[0]?.id ?? null, series_id: series[0]?.id ?? null,
      });
      editing = false;
    } catch (e) {
      saveError = e instanceof ApiError ? e.detail : $_("catalog.save_failed");
    } finally { busy = false; }
  }
</script>

<svelte:head><title>{party.name} — SetVault</title></svelte:head>

<article class="entity-detail">
  <header class="entity-head">
    <h1>{party.name}</h1>
    {#if !editing}
      {#if $session?.role === "admin"}
        <MonitorButton kind="party" entityId={party.id} name={party.name} monitor={data.party.monitor ?? null} />
        <button class="btn btn-ghost" on:click={startEdit}>{$_("catalog.edit")}</button>
      {/if}
    {/if}
  </header>
  {#if editing}
    <form class="entity-edit" on:submit|preventDefault={save}>
      <label>{$_("catalog.name")}<input bind:value={form.name} required /></label>
      <label>{$_("catalog.date")}<input type="date" bind:value={form.date} /></label>
      <div class="field" role="group" aria-labelledby="pe-venue">
        <span id="pe-venue">{$_("catalog.venue")}</span>
        <div class="with-clear">
          <EntityPicker kind="venue" allowCreate placeholder={$_("catalog.venue_placeholder")}
            bind:value={venue} on:create={(ev) => onCreate(ev, "venue")} />
          {#if venue.length}<button type="button" class="btn btn-ghost btn-sm" on:click={() => (venue = [])}>{$_("catalog.clear")}</button>{/if}
        </div>
      </div>
      <div class="field" role="group" aria-labelledby="pe-series">
        <span id="pe-series">{$_("catalog.series")}</span>
        <div class="with-clear">
          <EntityPicker kind="series" allowCreate placeholder={$_("catalog.series_placeholder")}
            bind:value={series} on:create={(ev) => onCreate(ev, "series")} />
          {#if series.length}<button type="button" class="btn btn-ghost btn-sm" on:click={() => (series = [])}>{$_("catalog.clear")}</button>{/if}
        </div>
      </div>
      <label>{$_("catalog.description")}<textarea bind:value={form.description}></textarea></label>
      {#if saveError}<p class="error" role="alert">{saveError}</p>{/if}
      <div class="actions">
        <button class="btn btn-primary" type="submit" disabled={busy}>{$_("catalog.save")}</button>
        <button class="btn btn-ghost" type="button" on:click={() => (editing = false)}>{$_("catalog.cancel")}</button>
      </div>
    </form>
  {:else}
    <p class="muted">
      {#if party.venue}<a href={`/venues/${party.venue.slug}`}>{party.venue.name}</a>{/if}
      {#if party.series} · <a href={`/series/${party.series.slug}`}>{party.series.name}</a>{/if}
      {#if party.date} · {party.date}{/if}
    </p>
    {#if party.description}<p>{party.description}</p>{/if}
  {/if}
  <h2>{$_("catalog.sets")}</h2>
  {#if data.sets.length}<EntitySetsGrid kind="parties" slug={data.party.slug} sets={data.sets} total={data.setsTotal} />{:else}<EmptyState message={$_("catalog.no_sets")} />{/if}
</article>

<style>
  .entity-detail { padding: var(--sp-6); display: grid; gap: var(--sp-4); max-width: 900px; }
  .entity-head { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-2); }
  .entity-edit { display: grid; gap: var(--sp-3); max-width: 480px; }
  .entity-edit label, .entity-edit .field { display: grid; gap: var(--sp-1); }
  .with-clear { display: flex; gap: var(--sp-2); align-items: flex-start; }
  .with-clear > :global(:first-child) { flex: 1; }
  .actions { display: flex; gap: var(--sp-2); }
  .muted { color: var(--text-faint); }
  .error { color: var(--accent-error); font-size: var(--ts-sm); }
</style>
