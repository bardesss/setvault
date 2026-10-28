<script lang="ts">
  import { tick } from "svelte";
  import { _ } from "svelte-i18n";
  import { beforeNavigate, goto } from "$app/navigation";
  import EntityPicker from "#lib/components/EntityPicker.svelte";
  import Modal from "#lib/components/Modal.svelte";
  import ConfirmDialog from "#lib/components/ConfirmDialog.svelte";
  import { toast } from "#lib/stores/toast.ts";
  import { formatDetail } from "#lib/api/errors.ts";
  import { ApiError } from "#lib/api/client.ts";
  import { patchSet } from "#lib/api/sets.ts";
  import { createArtist, createParty, createVenue, getParty } from "#lib/api/catalog.ts";
  import type { LookupRow } from "#lib/api/lookup.ts";
  import {
    SET_TYPES,
    diffPatch,
    formFromSet,
    roleOptions,
    type EditForm,
  } from "#lib/set-edit.ts";
  import type { PageData } from "./$types";

  export let data: PageData;

  const set = data.set;
  const slug = set.slug;
  const original: EditForm = formFromSet(set);
  const originalRoles: Record<string, string> = Object.fromEntries(
    original.artists.map((a) => [a.id, a.role]),
  );

  const asRow = (e: { id: string; name: string; slug: string }): LookupRow => ({
    id: e.id,
    name: e.name,
    slug: e.slug,
    hint: null,
  });
  // Tags are names; the id only keys the chip.
  const tagRow = (name: string): LookupRow => ({ id: `tag:${name}`, name, slug: name, hint: null });

  let title = original.title;
  let artists: LookupRow[] = original.artists.map(asRow);
  let roles: Record<string, string> = { ...originalRoles };
  let party: LookupRow[] = original.party ? [original.party] : [];
  let venue: LookupRow[] = original.venue ? [original.venue] : [];
  let date = original.date ?? "";
  let setType = original.set_type;
  let description = original.description ?? "";
  let tags: LookupRow[] = original.tags.map(tagRow);
  let series: { name: string; slug: string } | null = set.party?.series ?? null;

  let saving = false;
  let saved = false;
  let formError: string | null = null;
  let errorEl: HTMLElement | undefined;

  let current: EditForm;
  $: current = {
    title,
    artists: artists.map((a) => ({ ...a, role: roles[a.id] ?? "main" })),
    party: party[0] ?? null,
    venue: venue[0] ?? null,
    date: date || null,
    set_type: setType,
    description: description || null,
    tags: tags.map((t) => t.name),
  };
  $: patch = diffPatch(original, current);
  $: dirty = Object.keys(patch).length > 0;
  $: partyHref = party[0] ? `/parties/${party[0].slug}` : null;

  function errorText(e: unknown): string {
    return e instanceof ApiError ? formatDetail(e.detail) : String(e);
  }

  function createFailed(name: string, e: unknown) {
    toast.error($_("set_edit.create_failed", { values: { name, error: errorText(e) } }));
  }

  // --- artists -------------------------------------------------------
  function onArtistsChange(ev: CustomEvent<LookupRow[]>) {
    for (const a of ev.detail) roles[a.id] ??= "main";
  }

  async function onCreateArtist(ev: CustomEvent<{ name: string }>) {
    const { name } = ev.detail;
    try {
      const a = await createArtist(name);
      roles[a.id] = "main";
      artists = [...artists, asRow(a)];
    } catch (e) {
      createFailed(name, e);
    }
  }

  // --- party, venue, series -----------------------------------------
  let partySeq = 0;

  async function onPartyChange(picked: LookupRow | undefined) {
    const mine = ++partySeq;
    if (!picked) {
      series = null;
      return;
    }
    try {
      const p = await getParty(picked.slug);
      if (mine !== partySeq) return;
      series = p.series;
      if (p.venue && venue.length === 0) venue = [asRow(p.venue)];
    } catch {
      if (mine === partySeq) series = null;
    }
  }

  let partyModalOpen = false;
  let newParty = { name: "", date: "", venue: [] as LookupRow[] };
  let creatingParty = false;

  function onCreateParty(ev: CustomEvent<{ name: string }>) {
    newParty = { name: ev.detail.name, date, venue: [...venue] };
    partyModalOpen = true;
  }

  async function confirmCreateParty() {
    const name = newParty.name.trim();
    if (!name) return;
    creatingParty = true;
    try {
      const p = await createParty({
        name,
        date: newParty.date || null,
        venue_id: newParty.venue[0]?.id ?? null,
      });
      partySeq++;
      party = [asRow(p)];
      series = p.series;
      if (p.venue && venue.length === 0) venue = [asRow(p.venue)];
      partyModalOpen = false;
    } catch (e) {
      createFailed(name, e);
    } finally {
      creatingParty = false;
    }
  }

  async function onCreateVenue(ev: CustomEvent<{ name: string }>) {
    const { name } = ev.detail;
    try {
      venue = [asRow(await createVenue(name))];
    } catch (e) {
      createFailed(name, e);
    }
  }

  // --- tags ------------------------------------------------------------
  function onTagsChange(ev: CustomEvent<LookupRow[]>) {
    // A looked-up tag can repeat one already on the set (those carry no real id).
    const seen = new Set<string>();
    tags = ev.detail.filter((t) => {
      const key = t.name.trim().toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function onCreateTag(ev: CustomEvent<{ name: string }>) {
    tags = [...tags, tagRow(ev.detail.name)];
  }

  // --- save / leave ------------------------------------------------------
  async function showError(message: string) {
    formError = message;
    await tick();
    errorEl?.scrollIntoView({ block: "nearest" });
  }

  async function save() {
    if (!title.trim()) {
      await showError($_("set_edit.title_required"));
      return;
    }
    formError = null;
    if (!dirty) {
      await goto(`/sets/${slug}`);
      return;
    }
    saving = true;
    try {
      await patchSet(slug, patch);
      saved = true;
      toast.success($_("set_edit.saved"));
      await goto(`/sets/${slug}`);
    } catch (e) {
      await showError(
        e instanceof ApiError && e.status === 422 ? formatDetail(e.detail) : $_("set_edit.save_failed"),
      );
    } finally {
      saving = false;
    }
  }

  let leaveOpen = false;
  let leaveTo: URL | null = null;
  let leaving = false;

  beforeNavigate((nav) => {
    if (!dirty || saved || leaving) return;
    nav.cancel();
    // Closing the tab or leaving the app: the browser asks on its own.
    if (nav.type === "leave" || !nav.to) return;
    leaveTo = nav.to.url;
    leaveOpen = true;
  });

  async function confirmLeave() {
    leaveOpen = false;
    if (!leaveTo) return;
    leaving = true;
    await goto(leaveTo);
  }
</script>

<svelte:head><title>{$_("set_edit.page_title", { values: { title: set.title } })} - SetVault</title></svelte:head>

<article class="set-edit">
  <nav class="breadcrumb" aria-label={$_("set.breadcrumb")}>
    <a href={`/sets/${slug}`}>{set.title}</a>
    <span class="sep">›</span>
    <span class="current">{$_("set_edit.heading")}</span>
  </nav>
  <h1>{$_("set_edit.heading")}</h1>

  {#if formError}
    <p class="form-error" role="alert" bind:this={errorEl}>{formError}</p>
  {/if}

  <form on:submit|preventDefault={save}>
    <label class="field">
      <span class="label">{$_("set_edit.title")}</span>
      <input type="text" bind:value={title} maxlength="512" />
    </label>

    <div class="field" role="group" aria-labelledby="se-artists">
      <span class="label" id="se-artists">{$_("set_edit.artists")}</span>
      <EntityPicker
        kind="artist"
        multiple
        allowCreate
        placeholder={$_("set_edit.artists_placeholder")}
        bind:value={artists}
        on:change={onArtistsChange}
        on:create={onCreateArtist}
      >
        <svelte:fragment slot="chip" let:item>
          <select
            class="role"
            aria-label={$_("set_edit.role_for", { values: { name: item.name } })}
            value={roles[item.id] ?? "main"}
            on:change={(ev) => (roles = { ...roles, [item.id]: ev.currentTarget.value })}
          >
            {#each roleOptions(originalRoles[item.id] ?? "main") as r (r)}
              <option value={r}>{["main", "b2b"].includes(r) ? $_(`set.artist_role.${r}`) : r}</option>
            {/each}
          </select>
        </svelte:fragment>
      </EntityPicker>
    </div>

    <div class="row">
      <div class="field" role="group" aria-labelledby="se-party">
        <span class="label" id="se-party">{$_("set_edit.party")}</span>
        <div class="with-clear">
          <EntityPicker
            kind="party"
            allowCreate
            placeholder={$_("set_edit.party_placeholder")}
            bind:value={party}
            on:change={(ev) => onPartyChange(ev.detail[0])}
            on:create={onCreateParty}
          />
          {#if party.length > 0}
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              on:click={() => {
                party = [];
                void onPartyChange(undefined);
              }}>{$_("set_edit.clear")}</button
            >
          {/if}
        </div>
        {#if series}
          <p class="series">
            {$_("set_edit.series")}: <a href={`/series/${series.slug}`}>{series.name}</a>
            {#if partyHref}<span class="sep">·</span><a href={partyHref}>{$_("set_edit.edit_party")}</a>{/if}
          </p>
        {/if}
      </div>

      <div class="field" role="group" aria-labelledby="se-venue">
        <span class="label" id="se-venue">{$_("set_edit.venue")}</span>
        <div class="with-clear">
          <EntityPicker
            kind="venue"
            allowCreate
            placeholder={$_("set_edit.venue_placeholder")}
            bind:value={venue}
            on:create={onCreateVenue}
          />
          {#if venue.length > 0}
            <button type="button" class="btn btn-ghost btn-sm" on:click={() => (venue = [])}
              >{$_("set_edit.clear")}</button
            >
          {/if}
        </div>
      </div>
    </div>

    <div class="row">
      <div class="field" role="group" aria-labelledby="se-date">
        <span class="label" id="se-date">{$_("set_edit.date")}</span>
        <div class="with-clear">
          <input type="date" aria-labelledby="se-date" bind:value={date} />
          {#if date}
            <button type="button" class="btn btn-ghost btn-sm" on:click={() => (date = "")}
              >{$_("set_edit.clear")}</button
            >
          {/if}
        </div>
      </div>

      <label class="field">
        <span class="label">{$_("set_edit.set_type")}</span>
        <select bind:value={setType}>
          {#each SET_TYPES as t (t)}
            <option value={t}>{$_(`set_edit.type.${t}`)}</option>
          {/each}
        </select>
      </label>
    </div>

    <label class="field">
      <span class="label">{$_("set_edit.description")}</span>
      <textarea rows="5" bind:value={description}></textarea>
    </label>

    <div class="field" role="group" aria-labelledby="se-tags">
      <span class="label" id="se-tags">{$_("set_edit.tags")}</span>
      <EntityPicker
        kind="tag"
        multiple
        allowCreate
        placeholder={$_("set_edit.tags_placeholder")}
        bind:value={tags}
        on:change={onTagsChange}
        on:create={onCreateTag}
      />
    </div>

    <div class="actions">
      <button type="submit" class="btn btn-primary" disabled={saving}>
        {saving ? $_("set_edit.saving") : $_("set_edit.save")}
      </button>
      <a class="btn btn-ghost" href={`/sets/${slug}`}>{$_("common.cancel")}</a>
    </div>
  </form>
</article>

<Modal open={partyModalOpen} title={$_("set_edit.new_party")} on:close={() => (partyModalOpen = false)}>
  <form id="se-new-party" class="modal-form" on:submit|preventDefault={confirmCreateParty}>
    <label class="field">
      <span class="label">{$_("set_edit.party_name")}</span>
      <input type="text" bind:value={newParty.name} required />
    </label>
    <label class="field">
      <span class="label">{$_("set_edit.date")}</span>
      <input type="date" bind:value={newParty.date} />
    </label>
    <div class="field" role="group" aria-labelledby="se-new-party-venue">
      <span class="label" id="se-new-party-venue">{$_("set_edit.venue")}</span>
      <EntityPicker
        kind="venue"
        placeholder={$_("set_edit.venue_placeholder")}
        bind:value={newParty.venue}
      />
    </div>
  </form>
  <svelte:fragment slot="actions">
    <button type="button" class="btn" on:click={() => (partyModalOpen = false)}>
      {$_("common.cancel")}
    </button>
    <button
      type="submit"
      form="se-new-party"
      class="btn btn-primary"
      disabled={creatingParty || !newParty.name.trim()}
    >
      {$_("set_edit.create_party")}
    </button>
  </svelte:fragment>
</Modal>

<ConfirmDialog
  open={leaveOpen}
  title={$_("set_edit.unsaved_title")}
  message={$_("set_edit.unsaved_message")}
  confirmLabel={$_("set_edit.discard")}
  danger
  on:confirm={confirmLeave}
  on:cancel={() => (leaveOpen = false)}
/>

<style>
  .set-edit {
    padding: var(--sp-6);
    padding-bottom: calc(var(--shell-mini-player, 64px) + var(--sp-8));
    max-width: 760px;
    display: grid;
    gap: var(--sp-4);
  }
  .breadcrumb {
    display: flex;
    gap: var(--sp-2);
    font-size: var(--ts-sm);
    color: var(--text-muted);
    min-width: 0;
  }
  .breadcrumb a { color: var(--text-muted); text-decoration: none; }
  .breadcrumb a:hover { color: var(--text-default); }
  .breadcrumb .sep { color: var(--text-faintest); }
  .breadcrumb .current { color: var(--text-strong); }
  h1 { margin: 0; color: var(--text-strong); }
  form { display: grid; gap: var(--sp-4); }
  .modal-form { gap: var(--sp-3); }
  .field { display: grid; gap: var(--sp-1); min-width: 0; }
  .label { font-size: var(--ts-sm); color: var(--text-muted); }
  .row {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--sp-4);
  }
  .with-clear { display: flex; gap: var(--sp-2); align-items: flex-start; }
  .with-clear > :global(.picker) { flex: 1; min-width: 0; }
  .with-clear > input { flex: 1; min-width: 0; }
  input[type="text"],
  input[type="date"],
  select,
  textarea {
    padding: var(--sp-2) var(--sp-3);
    background: var(--bg-input);
    border: 1px solid var(--border-default);
    border-radius: var(--r-sm);
    color: var(--text-default);
    font: inherit;
  }
  input:focus,
  select:focus,
  textarea:focus {
    outline: none;
    border-color: var(--border-focus);
  }
  textarea { resize: vertical; }
  select.role {
    padding: 0 var(--sp-1);
    font-size: var(--ts-sm);
    background: transparent;
    border-color: var(--border-strong);
  }
  .series { margin: 0; font-size: var(--ts-sm); color: var(--text-muted); }
  .series a { color: var(--text-default); }
  .series .sep { margin: 0 var(--sp-2); color: var(--text-faintest); }
  .form-error {
    margin: 0;
    padding: var(--sp-3);
    border: 1px solid var(--accent-error);
    border-radius: var(--r-sm);
    color: var(--accent-error);
  }
  .actions { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
  @media (max-width: 600px) {
    .set-edit { padding: var(--sp-4); }
    .row { grid-template-columns: minmax(0, 1fr); }
  }
</style>
