<script lang="ts">
  import SectionHeader from "#lib/components/SectionHeader.svelte";
  import KpiGrid from "#lib/components/KpiGrid.svelte";
  import Kpi from "#lib/components/Kpi.svelte";
  import ContinueCard from "#lib/components/ContinueCard.svelte";
  import RecentCard from "#lib/components/RecentCard.svelte";
  import type { PageData } from "./$types";

  export let data: PageData;

  function fmtBytes(b: number): string {
    if (b <= 0) return "—";
    const gb = b / 1024 ** 3;
    if (gb >= 1) return `${gb.toFixed(0)}G`;
    const mb = b / 1024 ** 2;
    return `${mb.toFixed(0)}M`;
  }
  function fmtNumber(n: number): string {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return n.toString();
  }
  function fmtDelta(n: number, suffix: string = "this week"): string {
    if (n === 0) return `— 0 ${suffix}`;
    const sign = n > 0 ? "▲" : "▼";
    return `${sign} ${Math.abs(n)} ${suffix}`;
  }

  $: greeting = (() => {
    const h = new Date().getHours();
    if (h < 12) return "Morning";
    if (h < 18) return "Afternoon";
    return "Evening";
  })();

  $: userName =
    data.user?.display_name?.split(" ")[0] ||
    data.user?.email?.split("@")[0] ||
    "";
  $: summary = data.homeSummary;

  const NEW_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;
  function isNewSet(createdAt: string | undefined): boolean {
    if (!createdAt) return false;
    const t = Date.parse(createdAt);
    return !Number.isNaN(t) && Date.now() - t < NEW_WINDOW_MS;
  }
</script>

<svelte:head><title>SetVault</title></svelte:head>

{#if !data.user}
  <section class="anon">
    <h1>SetVault</h1>
    <p><a href="/login">Sign in</a> to access the library.</p>
  </section>
{:else}
  <header class="greet">
    <h1>
      {greeting}, <span class="accent">{userName}</span>.
      {#if summary && summary.sets_delta > 0}
        <b>{summary.sets_delta} new set{summary.sets_delta === 1 ? "" : "s"} landed in the last {summary.deltas_window_days} days.</b>
      {/if}
    </h1>
    {#if summary}
      <p class="sub">
        <b>{fmtNumber(summary.sets_count)} sets</b> · <b>{fmtNumber(summary.tracks_resolved_count)} tracks resolved</b>
      </p>

      <KpiGrid>
        <Kpi
          value={fmtNumber(summary.sets_count)}
          label="Sets in vault"
          delta={fmtDelta(summary.sets_delta)}
          deltaUp={summary.sets_delta > 0}
          accent={true}
        />
        <Kpi
          value={fmtNumber(summary.tracks_resolved_count)}
          label="Tracks resolved"
          delta={fmtDelta(summary.tracks_resolved_delta)}
          deltaUp={summary.tracks_resolved_delta > 0}
        />
        <Kpi
          value={fmtNumber(summary.tracks_needing_ids_count)}
          label="Tracks needing IDs"
          delta={fmtDelta(summary.tracks_needing_ids_delta)}
        />
        <Kpi
          value={fmtBytes(summary.audio_bytes)}
          label="Audio storage"
        />
      </KpiGrid>
    {/if}
  </header>

  {#if data.continueListening.length}
    <section class="home-section">
      <SectionHeader
        title="Continue where you left off"
        subMeta={`${data.continueListening.length} set${data.continueListening.length === 1 ? "" : "s"} in progress`}
      />
      <div class="continue">
        {#each data.continueListening as item (item.slug)}
          <ContinueCard
            slug={item.slug}
            title={item.title}
            positionSeconds={item.position_seconds}
            durationSeconds={item.duration_seconds}
          />
        {/each}
      </div>
    </section>
  {/if}

  <section class="home-section">
    <SectionHeader
      title="Recently added"
      subMeta={`${data.recent.length} recent`}
      moreHref="/sets"
      moreLabel="browse library →"
    />
    <div class="recent-grid">
      {#each data.recent as s (s.slug)}
        <RecentCard
          slug={s.slug}
          title={s.title}
          artist={Array.isArray(s.artists) && s.artists.length ? s.artists[0].name : ""}
          venue={s.venue?.name ?? ""}
          isNew={isNewSet(s.created_at)}
          year={s.date ? new Date(s.date).getFullYear() : null}
        />
      {/each}
    </div>
  </section>

  <!-- Phase 7: Activity feed + Jobs panel cells go here when the
       backend feed + WS streams land. Mockup section in 03-home.html
       lines ~480-670. -->
{/if}

<style>
  .anon {
    padding: var(--sp-8) var(--sp-6);
    display: grid;
    gap: var(--sp-3);
    max-width: 720px;
    margin: 0 auto;
  }
  .anon h1 {
    font-size: var(--ts-3xl);
    letter-spacing: var(--ls-tight);
    margin: 0;
  }
  .home-section {
    padding: var(--sp-6) var(--sp-8);
    border-bottom: 1px solid var(--border-subtle);
  }
</style>
