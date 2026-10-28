<script lang="ts">
  import { _ } from "svelte-i18n";
  import Player from "#lib/components/Player.svelte";
  import Tracklist from "#lib/components/Tracklist.svelte";
  import SidePanel from "#lib/components/SidePanel.svelte";
  import SetQuality from "#lib/components/SetQuality.svelte";
  import FavoriteButton from "#lib/components/FavoriteButton.svelte";
  import AddToPlaylist from "#lib/components/AddToPlaylist.svelte";
  import EmbedToggleAdmin from "#lib/components/EmbedToggleAdmin.svelte";
  import { session } from "#lib/stores/session.ts";
  import type { PageData } from "./$types";

  export let data: PageData;

  $: set = data.set;
  $: artistNames = set.artists.map((a) => a.name).join(", ") || "Unknown artist";
  $: isAdmin = $session?.role === "admin";
</script>

<svelte:head><title>{set.title} - SetVault</title></svelte:head>

<article class="set-detail">
  <!-- HERO -->
  <section class="set-hero">
    <nav class="breadcrumb" aria-label="Breadcrumb">
      <a href="/sets">Library</a>
      <span class="sep">›</span>
      <span class="current">{set.title}</span>
    </nav>

    <div class="set-title-row">
      <div>
        <h1 class="set-title">
          {set.title}<span class="by"> — {artistNames}</span>
        </h1>
        <div class="set-meta">
          {#if set.artists.length === 1}
            <a href={`/artists/${set.artists[0].slug}`}>{set.artists[0].name}</a>
          {:else}
            <a href="/search?q={encodeURIComponent(artistNames)}">{artistNames}</a>
          {/if}
          {#if set.venue}<span class="sep">@</span><a href={`/venues/${set.venue.slug}`}>{set.venue.name}</a>{/if}
          {#if set.party}<span class="sep">·</span><a href={`/parties/${set.party.slug}`}>{set.party.name}</a>{/if}
          {#if set.date}<span class="sep">·</span><span>{set.date}</span>{/if}
        </div>
      </div>
      <div class="set-title-actions">
        {#key set.slug}
          <FavoriteButton slug={set.slug} initial={set.is_favorite} />
          {#if $session}<AddToPlaylist slug={set.slug} />{/if}
        {/key}
        {#if $session}
          <a class="btn" href={`/sets/${set.slug}/edit`}>{$_("set_edit.edit")}</a>
        {/if}
        {#if isAdmin}
          <EmbedToggleAdmin slug={set.slug} allowed={set.embed_allowed} />
        {/if}
      </div>
    </div>

    <SetQuality {set} />

    {#if set.tags.length > 0}
      <div class="set-tags" aria-label="tags">
        {#each set.tags as tag (tag)}
          <span class="tag-pill">{tag}</span>
        {/each}
      </div>
    {/if}
  </section>

  <!-- PLAYER (wave-stage + transport) -->
  <Player {set} />

  {#if set.description}
    <section class="set-hero" style="border-bottom:none">
      <div class="side-section">
        <h4>About</h4>
        <p class="description">{set.description}</p>
      </div>
    </section>
  {/if}

  <!-- BODY: tracklist + engagement side panel -->
  <section class="body-grid">
    <Tracklist slug={set.slug} />
    <SidePanel slug={set.slug} />
  </section>
</article>

<style>
  .set-detail {
    padding-bottom: calc(var(--shell-mini-player, 64px) + var(--sp-8));
  }
  .description {
    margin: 0;
    color: var(--text-default);
    line-height: var(--lh-relaxed);
  }
  @media (max-width: 600px) {
    .set-detail {
      padding-bottom: calc(64px + var(--sp-4) + env(safe-area-inset-bottom, 0px));
    }
  }
</style>
